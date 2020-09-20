# This file is a part of pyctr.
#
# Copyright (c) 2017-2020 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

"""Module for interacting with contents in CDN layout."""

from enum import IntEnum
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from ..common import PyCTRError
from ..crypto import CryptoEngine, Keyslot, add_seed
from ..fileio import CloseWrapper
from .ncch import NCCHReader
from .tmd import TitleMetadataReader

if TYPE_CHECKING:
    from typing import BinaryIO, Dict, List, Union
    from ..crypto import CBCFileIO
    from .tmd import ContentChunkRecord


class CDNError(PyCTRError):
    """Generic error for CDN operations."""


class CDNSection(IntEnum):
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


class CDNRegion(NamedTuple):
    section: 'Union[int, CDNSection]'
    """Index of the section."""
    iv: bytes
    """Initialization vector. Only used for encrypted contents."""


class CDNReader:
    """
    Reads the contents of files in a CDN file layout.

    Only NCCH contents are supported. SRL (DSiWare) contents are currently ignored.

    Note that a custom :class:`~.CryptoEngine` object is only used for encryption on the CDN contents. Each
    :class:`~.NCCHReader` must use their own object, as it can only store keys for a single NCCH container. To
    use a custom one, set `load_contents` to `False`, then load each section manually with `open_raw_section`.

    :param file: A path to a tmd file. All the contents should be in the same directory.
    :param case_insensitive: Use case-insensitive paths for the RomFS of each NCCH container.
    :param crypto: A custom :class:`~.CryptoEngine` object to be used. Defaults to None, which causes a new one to
        be created. This is only used to decrypt the CIA, not the NCCH contents.
    :param dev: Use devunit keys.
    :param seed: Seed to use. This is a quick way to add a seed using :func:`~.seeddb.add_seed`.
    :param titlekey: Encrypted titlekey to use. Used over the ticket file if specified.
    :param decrypted_titlekey: Decrypted titlekey to use. Used over the encrypted titlekey or ticket if specified.
    :param common_key_index: Common key index to decrypt the titlekey with. Only used if `titlekey` is specified.
        Defaults to 0 for an eShop application.
    :param load_contents: Load each partition with :class:`~.NCCHReader`.
    """

    available_sections: 'List[Union[CDNSection, int]]'
    """A list of sections available, including contents, ticket, and title metadata."""

    closed = False
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

    def __init__(self, file: 'Union[PathLike, str, bytes]', *, case_insensitive: bool = False,
                 crypto: 'CryptoEngine' = None, dev: bool = False, seed: bytes = None, titlekey: bytes = None,
                 decrypted_titlekey: bytes = None, common_key_index: int = 0, load_contents: bool = True):
        if crypto:
            self._crypto = crypto
        else:
            self._crypto = CryptoEngine(dev=dev)

        # store the original open file to be closed later
        self._base_files = {}

        # public method to see what sections can be accessed
        self.available_sections = []

        def add_file(section: 'Union[CDNSection, int]', base, enc):
            self._base_files[section] = (base, enc)
            self.available_sections.append(section)

        tmd_file = Path(file)
        tmd_file_open = tmd_file.open('rb')
        title_root = tmd_file.parent
        add_file(CDNSection.TitleMetadata, tmd_file_open, None)

        # this is kinda eh
        self.tmd = TitleMetadataReader.load(tmd_file_open)
        tmd_file_open.seek(0)

        if seed:
            add_seed(self.tmd.title_id, seed)

        if decrypted_titlekey:
            self._crypto.set_normal_key(Keyslot.DecryptedTitlekey, decrypted_titlekey)
        elif titlekey:
            self._crypto.load_encrypted_titlekey(titlekey, common_key_index, self.tmd.title_id)
        else:
            ticket_file = title_root / 'cetk'
            ticket_file_open = ticket_file.open('rb')
            self._crypto.load_from_ticket(ticket_file_open.read(0x2AC))
            add_file(CDNSection.Ticket, ticket_file_open, None)
            ticket_file_open.seek(0)

        self.contents = {}
        self.content_info = []

        for record in self.tmd.chunk_records:
            iv = None
            if record.type.encrypted:
                iv = record.cindex.to_bytes(2, 'big') + (b'\0' * 14)
            # check if the content is a Nintendo DS ROM (SRL)
            is_srl = record.cindex == 0 and self.tmd.title_id[3:5] == '48'

            # allow both lowercase and uppercase contents
            content_lower = title_root / record.id
            content_upper = title_root / record.id.upper()
            if content_lower.is_file():
                to_read = content_lower
            elif content_upper.is_file():
                to_read = content_upper
            else:
                # can't find the file, so continue to the next record
                continue

            self.content_info.append(record)

            # this needs to check how many files are being opened
            if load_contents and not is_srl:
                base_file = to_read.open('rb')
                crypto_file = self._crypto.create_cbc_io(Keyslot.DecryptedTitlekey, base_file, iv)
                add_file(record.cindex, base_file, crypto_file)
                self.contents[record.cindex] = NCCHReader(crypto_file, case_insensitive=case_insensitive, dev=dev)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close the reader."""
        if not self.closed:
            self.closed = True
            for readers in self._base_files.values():
                readers[0].close()
                if readers[1]:
                    readers[1].close()

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

    def open_raw_section(self, section: 'Union[int, CDNSection]') -> 'BinaryIO':
        """
        Open a raw CDN content for reading with on-the-fly decryption.

        :param section: The content to open.
        :return: A file-like object that reads from the content.
        :rtype: io.BufferedIOBase | CBCFileIO
        """
        if section >= 0:
            return CloseWrapper(self._base_files[section][1])
        else:
            return CloseWrapper(self._base_files[section][0])
