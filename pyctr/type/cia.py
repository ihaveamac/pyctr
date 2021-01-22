# This file is a part of pyctr.
#
# Copyright (c) 2017-2021 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

"""Module for interacting with CTR Importable Archive (CIA) files."""

from enum import IntEnum
from io import BytesIO
from threading import Lock
from typing import TYPE_CHECKING, NamedTuple

from ..common import PyCTRError
from ..crypto import CryptoEngine, Keyslot, add_seed
from ..fileio import SubsectionIO
from ..type.ncch import NCCHReader
from ..type.tmd import TitleMetadataReader
from ..util import readle, roundup
from .base import TypeReaderCryptoBase

if TYPE_CHECKING:
    from os import PathLike
    from typing import BinaryIO, Dict, List, Optional, Union
    from .tmd import ContentChunkRecord

ALIGN_SIZE = 64


class CIAError(PyCTRError):
    """Generic error for CIA operations."""


class InvalidCIAError(CIAError):
    """Invalid CIA header exception."""


class CIASection(IntEnum):
    """Sections of a CIA file. Values 0 and above are only for the most common types, and do not apply to DLC titles."""
    # these values as negative, as positive ones are used for contents
    ArchiveHeader = -4
    """Contains the sizes of all the other sections."""
    CertificateChain = -3
    """Contains signatures used to verify the Ticket and Title Metadata."""
    Ticket = -2
    """
    Contains the title key used to decrypt the contents, as well as a content index describing which contents are 
    enabled (mostly used for DLC).
    """
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
    Meta = -5


class CIARegion(NamedTuple):
    section: 'Union[int, CIASection]'
    """Index of the section."""
    offset: int
    """Offset of the entry, relative to the end of the header."""
    size: int
    """Size of the entry data."""
    iv: bytes
    """Initialization vector. Only used for encrypted contents."""


class CIAReader(TypeReaderCryptoBase):
    """
    Reads the contents of CIA files. The sources of these are usually dumps from digital titles from Nintendo eShop or
    the update CDN, gamecard update partitions, or Download Play children.

    Only NCCH contents are supported. SRL (DSiWare) contents are currently ignored.

    CIA files contain:

    - a 0x20-byte header with sizes for all the following sections
    - an archive header where each bit is an enabled content
    - a Certificate chain to verify the signatures in all the following sections
    - a Ticket with a titlekey to decrypt the contents
    - a Title Metadata (TMD) that contains information about all the possible contents
    - the contents themselves
    - an optional Meta region

    In executable titles, the first content is the CTR Executable Image (CXI), second is a manual in a CTR File Archive
    (CFA), and third is a Download Play child container in a CFA. In DLC titles (tid-high is 0004008c),
    the first content has meta information about each content, then the rest contain the DLC content. All contents are
    CFAs. In system archives, the first (and only) content is a CFA.

    CIA files do not always contain all the contents in the TMD, especially in dumped DLC titles. Which contents are in
    the archive is indicated in the archive header.

    Note that a custom :class:`~.CryptoEngine` object is only used for encryption on the CIA contents. Each
    :class:`~.NCCHReader` must use their own object, as it can only store keys for a single NCCH container. To
    use a custom one, set `load_contents` to `False`, then load each section manually with `open_raw_section`.

    :param file: A file path or a file-like object with the CIA data.
    :param case_insensitive: Use case-insensitive paths for the RomFS of each NCCH container.
    :param crypto: A custom :class:`~.CryptoEngine` object to be used. Defaults to None, which causes a new one to
        be created. This is only used to decrypt the CIA, not the NCCH contents.
    :param dev: Use devunit keys.
    :param seed: Seed to use. This is a quick way to add a seed using :func:`~.seeddb.add_seed`.
    :param load_contents: Load each partition with :class:`~.NCCHReader`.
    """

    contents: 'Dict[int, NCCHReader]'
    """A `dict` of :class:`~.NCCHReader` objects for each active NCCH content."""

    content_info: 'List[ContentChunkRecord]'
    """A list of :class:`~.ContentChunkRecord` objects for each active content."""

    sections: 'Dict[Union[int, CIASection], CIARegion]'
    """A list of :class:`CIARegion` objects containing the offset and size of each section."""

    tmd: TitleMetadataReader
    """The :class:`~.TitleMetadataReader` object with information from the TMD section."""

    total_size: int
    """Expected size of the CIA file in bytes."""

    def __init__(self, file: 'Union[PathLike, str, bytes, BinaryIO]', *, closefd: bool = None,
                 case_insensitive: bool = True, crypto: CryptoEngine = None, dev: bool = False, seed: bytes = False,
                 load_contents: bool = True):
        super().__init__(file, closefd=closefd, crypto=crypto, dev=dev)

        # Threading lock to prevent two operations on one class instance from interfering with eachother.
        self._lock = Lock()

        # store case-insensitivity for RomFSReader
        self._case_insensitive = case_insensitive

        header = self._file.read(0x20)

        archive_header_size = readle(header[0x0:0x4])
        if archive_header_size != 0x2020:
            raise InvalidCIAError('Archive Header Size is not 0x2020')
        # in practice, the certificate chain is the same for all retail titles
        cert_chain_size = readle(header[0x8:0xC])
        # the ticket size usually never changes from 0x350
        # there is one ticket (without an associated title) that is smaller though
        ticket_size = readle(header[0xC:0x10])
        # tmd contains info about the contents of the title
        tmd_size = readle(header[0x10:0x14])
        # meta contains info such as the SMDH and Title ID dependency list
        meta_size = readle(header[0x14:0x18])
        # content size is the total size of the contents
        # I'm not sure what happens yet if one of the contents is not aligned to 0x40 bytes.
        content_size = readle(header[0x18:0x20])
        # the content index determines what contents are in the CIA
        # this is not stored as int, so it's faster to parse(?)
        content_index = self._file.read(archive_header_size - 0x20)

        active_contents = set()
        for idx, b in enumerate(content_index):
            offset = idx * 8
            curr = b
            for x in range(7, -1, -1):
                if curr & 1:
                    active_contents.add(x + offset)
                curr >>= 1

        # the header only stores sizes; offsets need to be calculated.
        # the sections are aligned to 64(0x40) bytes. for example, if something is 0x78,
        #   it will take up 0x80, with the remaining 0x8 being padding.
        cert_chain_offset = roundup(archive_header_size, ALIGN_SIZE)
        ticket_offset = cert_chain_offset + roundup(cert_chain_size, ALIGN_SIZE)
        tmd_offset = ticket_offset + roundup(ticket_size, ALIGN_SIZE)
        content_offset = tmd_offset + roundup(tmd_size, ALIGN_SIZE)
        meta_offset = content_offset + roundup(content_size, ALIGN_SIZE)

        # lazy method to get the total size
        self.total_size = meta_offset + meta_size

        # this contains the location of each section, as well as the IV of encrypted ones
        self.sections = {}

        def add_region(section: 'Union[int, CIASection]', offset: int, size: int, iv: 'Optional[bytes]'):
            region = CIARegion(section=section, offset=offset, size=size, iv=iv)
            self.sections[section] = region

        # add each part of the header
        add_region(CIASection.ArchiveHeader, 0, archive_header_size, None)
        add_region(CIASection.CertificateChain, cert_chain_offset, cert_chain_size, None)
        add_region(CIASection.Ticket, ticket_offset, ticket_size, None)
        add_region(CIASection.TitleMetadata, tmd_offset, tmd_size, None)
        if meta_size:
            add_region(CIASection.Meta, meta_offset, meta_size, None)

        # this will load the titlekey to decrypt the contents
        self._file.seek(self._start + ticket_offset)
        ticket = self._file.read(ticket_size)
        self._crypto.load_from_ticket(ticket)

        # the tmd describes the contents: ID, index, size, and hash
        self._file.seek(self._start + tmd_offset)
        tmd_data = self._file.read(tmd_size)
        self.tmd = TitleMetadataReader.load(BytesIO(tmd_data))

        if seed:
            add_seed(self.tmd.title_id, seed)

        active_contents_tmd = set()
        self.content_info = []

        # this does a first check to make sure there are no missing contents that are marked active in content_index
        for record in self.tmd.chunk_records:
            if record.cindex in active_contents:
                active_contents_tmd.add(record.cindex)
                self.content_info.append(record)

        # if the result of this is not an empty set, it means there are contents enabled in content_index
        #   that are not in the tmd, which is bad
        if active_contents ^ active_contents_tmd:
            raise InvalidCIAError('Missing active contents in the TMD')

        self.contents = {}

        # this goes through the contents and figures out their regions, then creates an NCCHReader
        curr_offset = content_offset
        for record in self.content_info:
            iv = None
            if record.type.encrypted:
                iv = record.cindex.to_bytes(2, 'big') + (b'\0' * 14)
            add_region(record.cindex, curr_offset, record.size, iv)
            if load_contents:
                # check if the content is a Nintendo DS ROM (SRL) first
                is_srl = record.cindex == 0 and self.tmd.title_id[3:5] == '48'
                if not is_srl:
                    content_fp = self.open_raw_section(record.cindex)
                    self.contents[record.cindex] = NCCHReader(content_fp, case_insensitive=case_insensitive,
                                                              dev=dev)

            curr_offset += record.size

    def __repr__(self):
        info = [('title_id', self.tmd.title_id)]
        try:
            info.append(('title_name', repr(self.contents[0].exefs.icon.get_app_title().short_desc)))
        except KeyError:
            info.append(('title_name', 'unknown'))
        info.append(('content_count', len(self.contents)))
        info_final = " ".join(x + ": " + str(y) for x, y in info)
        return f'<{type(self).__name__} {info_final}>'

    def open_raw_section(self, section: 'Union[int, CIASection]'):
        """
        Open a raw CIA section for reading with on-the-fly decryption.

        :param section: The section to open.
        :return: A file-like object that reads from the section.
        :rtype: SubsectionIO
        """
        region = self.sections[section]
        fh = SubsectionIO(self._file, self._start + region.offset, region.size)
        if region.iv:
            fh = self._crypto.create_cbc_io(Keyslot.DecryptedTitlekey, fh, region.iv)
        return fh
