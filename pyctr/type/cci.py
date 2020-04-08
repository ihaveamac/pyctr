# This file is a part of pyctr.
#
# Copyright (c) 2017-2020 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

"""Module for interacting with CTR Cart Image (CCI) files."""

from enum import IntEnum
from os import PathLike
from typing import TYPE_CHECKING, NamedTuple

from ..common import PyCTRError
from ..fileio import SubsectionIO
from ..type.ncch import NCCHReader
from ..util import readle
from .base import TypeReaderBase

if TYPE_CHECKING:
    from typing import BinaryIO, Dict, Union

CCI_MEDIA_UNIT = 0x200


class CCIError(PyCTRError):
    """Generic error for CCI operations."""


class InvalidCCIError(CCIError):
    """Invalid CCI header exception."""


class CCISection(IntEnum):
    """Partition indexes in a CCI."""
    Header = -3
    """Header of the CCI file."""
    CardInfo = -2
    """Card Info Header. https://www.3dbrew.org/wiki/NCSD#Card_Info_Header"""
    DevInfo = -1
    """
    Development Card Info Header. Some flashcarts use this for "private headers" which are unique to each produced
    game card.
    """
    Application = 0
    """Main application CXI."""
    Manual = 1
    """Manual CFA. It has a RomFS with a single "Manual.bcma" file inside."""
    DownloadPlayChild = 2
    """
    Download Play Child CFA. It has a RomFS with CIA files that are sent to other Nintendo 3DS systems using
    Download Play. Most games only contain one.
    """
    Unk3 = 3
    """Never seems to be used in practice."""
    Unk4 = 4
    """Never seems to be used in practice."""
    Unk5 = 5
    """Never seems to be used in practice."""
    UpdateNew3DS = 6
    """
    Update CFA for New Nintendo 3DS systems. It has a RomFS with a "SNAKE" directory, then contains the same as
    :attr:`UpdateOld3DS`. Any Title IDs in "cup_list" that are not in this partition are loaded from 
    :attr:`UpdateOld3DS`.
    """
    UpdateOld3DS = 7
    """
    Update CFA for Old Nintendo 3DS systems. It has a RomFS with a "cup_list" file that is 0x800 bytes and is a list of
    Title IDs in the update. The rest are CIA files with matching Title ID filenames.
    """


class CCIRegion(NamedTuple):
    section: 'CCISection'
    offset: int
    size: int


class CCIReader(TypeReaderBase):
    """
    Reads the contents of CCI files, usually dumps from Nintendo 3DS game cards.

    A CCI file can contain 8 partitions; in practice, only 0, 1, 2, 6 and 7 seem to be used.

    Note that a custom :class:`~.CryptoEngine` object cannot be given, as it can only store keys for a single
    :class:`~.NCCHReader`. To use a custom one, set `load_contents` to `False`, then load each section manually
    with `open_raw_section`.

    :param file: A file path or a file-like object with the CCI data.
    :param case_insensitive: Use case-insensitive paths for the RomFS of each NCCH container.
    :param dev: Use devunit keys.
    :param load_contents: Load each partition with :class:`~.NCCHReader`.
    :param assume_decrypted: Assume each NCCH content is decrypted. Needed if the image was decrypted without fixing
        the NCCH flags.
    """

    closed = False
    """`True` if the reader is closed."""

    image_size: int
    """Image size in bytes. This does not always match the file size on disk."""

    sections: 'Dict[CCISection, CCIRegion]'
    """A list of :class:`CCIRegion` objects containing the offset and size of each partition."""

    contents: 'Dict[CCISection, NCCHReader]'
    """A list of :class:`~.NCCHReader` objects for each partition."""

    media_id: str
    """Same as the Title ID of the application."""

    def __init__(self, file: 'Union[PathLike, str, bytes, BinaryIO]', *, closefd: bool = None,
                 case_insensitive: bool = True, dev: bool = False, load_contents: bool = True,
                 assume_decrypted: bool = False):
        super().__init__(file, closefd=closefd)

        # store case-insensitivity for RomFSReader
        self._case_insensitive = case_insensitive

        # ignore the signature, we don't need it
        self._file.seek(0x100, 1)
        header = self._file.read(0x100)
        if header[0:4] != b'NCSD':
            raise InvalidCCIError('NCSD magic not found')

        # make sure the Media ID is not 00, which is used for the NAND header
        self.media_id = header[0x8:0x10][::-1].hex()
        if self.media_id == '00' * 8:
            raise InvalidCCIError('Not a CCI, this is a NAND')

        self.image_size = readle(header[4:8]) * CCI_MEDIA_UNIT

        # this contains the location of each section
        self.sections = {}

        # this contains loaded sections
        self.contents = {}

        def add_region(section: 'CCISection', offset: int, size: int):
            region = CCIRegion(section=section, offset=offset, size=size)
            self.sections[section] = region

        # add each part of the header
        add_region(CCISection.Header, 0, 0x200)
        add_region(CCISection.CardInfo, 0x200, 0x1000)
        add_region(CCISection.DevInfo, 0x1200, 0x300)

        # use a CCISection value for section keys
        partition_sections = [x for x in CCISection if x >= 0]

        part_raw = header[0x20:0x60]

        # the first content always starts at 0x4000 but this code makes no assumptions about it
        for idx, info_offset in enumerate(range(0, 0x40, 0x8)):
            part_info = part_raw[info_offset:info_offset + 8]
            part_offset = readle(part_info[0:4]) * CCI_MEDIA_UNIT
            part_size = readle(part_info[4:8]) * CCI_MEDIA_UNIT
            if part_offset:
                section_id = partition_sections[idx]
                add_region(section_id, part_offset, part_size)

                if load_contents:
                    content_fp = self.open_raw_section(section_id)
                    self.contents[section_id] = NCCHReader(content_fp, case_insensitive=case_insensitive, dev=dev,
                                                           assume_decrypted=assume_decrypted)

    def __repr__(self):
        info = [('media_id', self.media_id)]
        try:
            info.append(('title_name',
                         repr(self.contents[CCISection.Application].exefs.icon.get_app_title().short_desc)))
        except KeyError:
            info.append(('title_name', 'unknown'))
        info.append(('partition_count', len(self.contents)))
        info_final = " ".join(x + ": " + str(y) for x, y in info)
        return f'<{type(self).__name__} {info_final}>'

    def open_raw_section(self, section: 'CCISection'):
        """
        Open a raw CCI section for reading.

        :param section: The section to open.
        :return: A file-like object that reads from the section.
        :rtype: SubsectionIO
        """
        region = self.sections[section]
        return SubsectionIO(self._file, self._start + region.offset, region.size)
