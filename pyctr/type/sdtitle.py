# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from enum import IntEnum
from os import fsdecode
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from weakref import WeakSet

from ..common import PyCTRError
from ..crypto import add_seed
from .ncch import NCCHReader
from .tmd import TitleMetadataReader

if TYPE_CHECKING:
    from pathlib import PurePath
    from typing import BinaryIO, Dict, List, Set, Union

    from ..common import FilePath
    from .ncch import NCCHReader
    from .sd import SDFilesystem
    from .tmd import ContentChunkRecord


class SDTitleError(PyCTRError):
    """Generic error for SD Title operations."""


class SDTitleSection(IntEnum):
    TitleMetadata = -1
    """Contains information about all the possible contents."""
    Application = 0
    """Main application CXI."""
    Manual = 1
    """Manual CFA. It has a RomFS with a single "Manual.bcma" file inside."""
    DownloadPlayChild = 2
    """
    Download Play Child CFA. It has a RomFS with CIA files that are sent to other Nintendo 3DS systems using
    Download Play. Most games only contain one.
    """


class SDTitleReader:
    """
    Reads the contents of files installed on the SD card inside "Nintendo 3DS".

    By default, this only works with contents that do not use SD encryption (i.e. tmd and contents are plaintext). To
    read contents currently encrypted on an SD card, :class:`~.SDFilesystem` is needed, and provides a method to easily
    open a title's contents. (NYI)

    Only NCCH contents are supported. SRL (DSiWare) contents are currently ignored.

    :param file: A path to a tmd file. All the contents should be in the same directory.
    :param case_insensitive: Use case-insensitive paths for the RomFS of each NCCH container.
    :param dev: Use devunit keys.
    :param seed: Seed to use. This is a quick way to add a seed using :func:`~.seeddb.add_seed`.
    :param load_contents: Load each partition with :class:`~.NCCHReader`.
    :param sdfs: :class:`~.SDFilesystem` object to use, if opening contents that are currently encrypted. Usually this
        should not be set directly, instead open the title through :class:`~.SDFilesystem`. (NYI)
    :param sd_id1: ID1 to use if opened through :class:`~.SDFilesystem`.
    """

    __slots__ = (
        '_base_files', '_open_files', 'available_sections', 'closed', 'content_info', 'contents', 'sd_id1', 'sdfs',
        'tmd'
    )

    available_sections: 'List[Union[SDTitleSection, int]]'
    """A list of sections available, including contents, ticket, and title metadata."""

    closed: bool
    """`True` if the reader is closed."""

    contents: 'Dict[int, NCCHReader]'
    """A `dict` of :class:`~.NCCHReader` objects for each active NCCH content."""

    content_info: 'List[ContentChunkRecord]'
    """
    A list of :class:`~.ContentChunkRecord` objects for each content found in the directory at the time of object
    initialization.
    """

    tmd: TitleMetadataReader
    """The :class:`~.TitleMetadataReader` object with information from the TMD section."""

    def __init__(self, file: 'FilePath', *, case_insensitive: bool = False, dev: bool = False, seed: bytes = None,
                 load_contents: bool = True, sdfs: 'SDFilesystem' = None, sd_id1: str = None):
        self.closed = False

        self.sdfs = sdfs
        self.sd_id1 = sd_id1

        self.contents = {}
        self.content_info = []

        # {section: filepath}
        self._base_files: Dict[Union[SDTitleSection, int], PurePath] = {}

        # opened files to close if the SDTitleReader is closed
        # noinspection PyTypeChecker
        self._open_files: Set[BinaryIO] = WeakSet()

        # public method to see what sections can be accessed
        self.available_sections = []

        if self.sdfs:
            file = PurePosixPath(file)
        else:
            file = Path(fsdecode(file)).absolute()
        title_root = file.parent

        def add_file(section: 'Union[SDTitleSection, int]', path: "PurePath"):
            self._base_files[section] = path
            self.available_sections.append(section)

        add_file(SDTitleSection.TitleMetadata, file)

        with self.open_raw_section(SDTitleSection.TitleMetadata) as tmd:
            self.tmd = TitleMetadataReader.load(tmd)

        if seed:
            add_seed(self.tmd.title_id, seed)

        for record in self.tmd.chunk_records:
            # check if the content is a Nintendo DS ROM (SRL)
            is_srl = record.cindex == 0 and self.tmd.title_id[3:5] == '48'

            # this should ideally never be uppercase in practice
            # since the console stores these as lowercase
            content_file = title_root / (record.id + '.app')
            if self.sdfs:
                if not self.sdfs.isfile(str(content_file), id1=self.sd_id1):
                    # can't find the file, so continue to the next record
                    continue
            else:
                if not content_file.is_file():
                    continue

            self.content_info.append(record)
            add_file(record.cindex, content_file)

            # this needs to check how many files are being opened
            if load_contents and not is_srl:
                decrypted_file = self.open_raw_section(record.cindex)
                self.contents[record.cindex] = NCCHReader(decrypted_file, case_insensitive=case_insensitive, dev=dev)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close the reader."""
        if not self.closed:
            self.closed = True
            for cindex, content in self.contents.items():
                content.close()
            for f in self._open_files:
                f.close()

            self.contents = {}
            # frozenset can't be modified, so even if I made a mistake this prevents opening files on a closed reader
            self._open_files = frozenset()

    __del__ = close

    def __repr__(self):
        info = [('title_id', self.tmd.title_id)]
        try:
            info.append(('title_name', repr(self.contents[0].exefs.icon.get_app_title().short_desc)))
        except KeyError:
            info.append(('title_name', 'unknown'))
        info.append(('content_count', len(self.contents)))
        info_final = " ".join(x + ": " + str(y) for x, y in info)
        return f'<{type(self).__name__} {info_final}>'

    def open_raw_section(self, section: 'Union[SDTitleSection, int]') -> 'BinaryIO':
        """
        Open a raw content for reading.

        :param section: The content to open.
        :return: A file-like object that reads from the content.
        :rtype: io.BufferedIOBase | CTRFileIO
        """
        filepath = self._base_files[section]
        if self.sdfs:
            f = self.sdfs.open(str(filepath), 'rb', id1=self.sd_id1)
        else:
            f = open(filepath, 'rb')
        self._open_files.add(f)
        return f
