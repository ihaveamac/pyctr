# This file is a part of pyctr.
#
# Copyright (c) 2017-2020 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from enum import IntEnum
from io import BytesIO
from os import PathLike
from threading import Lock
from typing import TYPE_CHECKING, NamedTuple

from ..common import PyCTRError
from ..crypto import CryptoEngine, Keyslot
from ..fileio import SubsectionIO
from ..type.ncch import NCCHReader
from ..type.tmd import TitleMetadataReader
from ..util import readle, roundup

if TYPE_CHECKING:
    from typing import BinaryIO, Dict, Optional, Union

ALIGN_SIZE = 64


class CIAError(PyCTRError):
    """Generic error for CIA operations."""


class InvalidCIAError(CIAError):
    """Invalid CIA header exception."""


class CIASection(IntEnum):
    # these values as negative, as positive ones are used for contents
    ArchiveHeader = -4
    CertificateChain = -3
    Ticket = -2
    TitleMetadata = -1
    Application = 0
    Manual = 1
    DownloadPlayChild = 2
    Meta = -5


class CIARegion(NamedTuple):
    section: 'Union[int, CIASection]'
    offset: int
    size: int
    iv: bytes  # only used for encrypted sections


class CIAReader:
    """
    Reads the contents of CTR Importable Archive files. The sources of these are usually dumps from digital titles from
    Nintendo eShop or the update CDN, gamecard update partitions, or Download Play children.

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

    Note that a custom :class:`crypto.CryptoEngine` object is only used for encryption on the CIA contents. Each
    :class:`type.ncch.NCCHReader` must use their own object, as it can only store keys for a single NCCH container. To
    use a custom one, set `load_contents` to `False`, then load each section manually with `open_raw_section`.

    :param fp: A file path or a file-like object with the CIA data.
    :param case_insensitive: Use case-insensitive paths for the RomFS of each NCCH container.
    :param crypto: A custom :class:`crypto.CryptoEngine` object to be used. Defaults to None, which causes a new one to
        be created. This is only used to decrypt the CIA, not the NCCH contents.
    :param dev: Use devunit keys.
    :param seeddb: Path to a SeedDB file.
    :param load_contents: Load each partition with :class:`type.ncch.NCCHReader`.
    :ivar contents: A `dict` of :class:`type.ncch.NCCHReader` objects for each active NCCH content.
    :ivar content_info: A list of :class:`type.tmd.ContentChunkRecord` objects for each active content.
    :ivar tmd: The :class:`type.tmd.TitleMetadataReader` object with information from the TMD section.
    :ivar sections: A list of :class:`CIARegion` objects containing the offset and size of each section.
    :ivar total_size: Expected size of the CIA file in bytes.
    """

    closed = False

    def __init__(self, fp: 'Union[PathLike, str, bytes, BinaryIO]', *, case_insensitive: bool = True,
                 crypto: CryptoEngine = None, dev: bool = False, seeddb: str = None, load_contents: bool = True):
        if isinstance(fp, (PathLike, str, bytes)):
            fp = open(fp, 'rb')

        if crypto:
            self._crypto = crypto
        else:
            self._crypto = CryptoEngine(dev=dev)

        # store the starting offset so the CIA can be read from any point in the base file
        self._start = fp.tell()
        self._fp = fp
        # store case-insensitivity for RomFSReader
        self._case_insensitive = case_insensitive
        # threading lock
        self._lock = Lock()

        header = fp.read(0x20)

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
        content_index = fp.read(archive_header_size - 0x20)

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
        self.sections: Dict[Union[int, CIASection], CIARegion] = {}

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
        self._fp.seek(self._start + ticket_offset)
        ticket = self._fp.read(ticket_size)
        self._crypto.load_from_ticket(ticket)

        # the tmd describes the contents: ID, index, size, and hash
        self._fp.seek(self._start + tmd_offset)
        tmd_data = self._fp.read(tmd_size)
        self.tmd = TitleMetadataReader.load(BytesIO(tmd_data))

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
                                                              dev=dev, seeddb=seeddb)

            curr_offset += record.size

    def close(self):
        self.closed = True
        try:
            self._fp.close()
        except AttributeError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

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

    def open_raw_section(self, section: 'CIASection'):
        """
        Open a raw CIA section for reading with on-the-fly decryption.

        :param section: The section to open.
        :return: A file-like object that reads from the section.
        :rtype: SubsectionIO
        """
        region = self.sections[section]
        fh = SubsectionIO(self._fp, self._start + region.offset, region.size)
        if region.iv:
            fh = self._crypto.create_cbc_io(Keyslot.DecryptedTitlekey, fh, region.iv)
        return fh
