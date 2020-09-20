# This file is a part of pyctr.
#
# Copyright (c) 2017-2020 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

"""Module for interacting with Read-only Filesystem (RomFS) files."""

from io import TextIOWrapper
from os import PathLike
from typing import overload, TYPE_CHECKING, NamedTuple

from ..common import PyCTRError
from ..fileio import SubsectionIO
from ..util import readle, roundup
from .base import TypeReaderBase

if TYPE_CHECKING:
    from typing import BinaryIO, Optional, Tuple, Union

__all__ = ['IVFC_HEADER_SIZE', 'IVFC_ROMFS_MAGIC_NUM', 'ROMFS_LV3_HEADER_SIZE', 'RomFSError', 'InvalidIVFCError',
           'InvalidRomFSHeaderError', 'RomFSEntryError', 'RomFSFileNotFoundError', 'RomFSReader']

IVFC_HEADER_SIZE = 0x5C
IVFC_ROMFS_MAGIC_NUM = 0x10000
ROMFS_LV3_HEADER_SIZE = 0x28


class RomFSError(PyCTRError):
    """Generic exception for RomFS operations."""


class InvalidIVFCError(RomFSError):
    """Invalid IVFC header exception."""


class InvalidRomFSHeaderError(RomFSError):
    """Invalid RomFS Level 3 header."""


class RomFSEntryError(RomFSError):
    """Error with RomFS Directory or File entry."""


class RomFSFileNotFoundError(RomFSEntryError):
    """Invalid file path in RomFS Level 3."""


class RomFSIsADirectoryError(RomFSEntryError):
    """Attempted to open a directory as a file."""


class RomFSRegion(NamedTuple):
    offset: int
    size: int


class RomFSDirectoryEntry(NamedTuple):
    name: str
    type: str
    contents: 'Tuple[str, ...]'


class RomFSFileEntry(NamedTuple):
    name: str
    type: str
    offset: int
    size: int


class RomFSReader(TypeReaderBase):
    """
    Reads the contents of the RomFS, found inside NCCH containers.

    The RomFS found inside an NCCH is wrapped in an IVFC hash-tree container. This class only supports Level 3, which
    contains the actual files.

    :param file: A file path or a file-like object with the RomFS data.
    :param case_insensitive: Use case-insensitive paths.
    :param closefd: Close the underlying file object when closed. Defaults to `True` for file paths, and `False` for
        file-like objects.
    """

    lv3_offset = 0
    data_offset = 0

    def __init__(self, file: 'Union[PathLike, str, bytes, BinaryIO]', case_insensitive: bool = False, *,
                 closefd: bool = None):
        super().__init__(file, closefd=closefd)

        self.case_insensitive = case_insensitive

        lv3_offset = self._file.tell()
        magic = self._file.read(4)

        # detect ivfc and get the lv3 offset
        if magic == b'IVFC':
            ivfc = magic + self._file.read(0x54)  # IVFC_HEADER_SIZE - 4
            ivfc_magic_num = readle(ivfc[0x4:0x8])
            if ivfc_magic_num != IVFC_ROMFS_MAGIC_NUM:
                raise InvalidIVFCError(f'IVFC magic number is invalid '
                                       f'({ivfc_magic_num:#X} instead of {IVFC_ROMFS_MAGIC_NUM:#X})')
            master_hash_size = readle(ivfc[0x8:0xC])
            lv3_block_size = readle(ivfc[0x4C:0x50])
            lv3_hash_block_size = 1 << lv3_block_size
            lv3_offset += roundup(0x60 + master_hash_size, lv3_hash_block_size)
            self._file.seek(self._start + lv3_offset)
            magic = self._file.read(4)
        self.lv3_offset = lv3_offset

        lv3_header = magic + self._file.read(0x24)  # ROMFS_LV3_HEADER_SIZE - 4

        # get offsets and sizes from lv3 header
        lv3_header_size = readle(magic)
        lv3_dirhash = RomFSRegion(offset=readle(lv3_header[0x4:0x8]), size=readle(lv3_header[0x8:0xC]))
        lv3_dirmeta = RomFSRegion(offset=readle(lv3_header[0xC:0x10]), size=readle(lv3_header[0x10:0x14]))
        lv3_filehash = RomFSRegion(offset=readle(lv3_header[0x14:0x18]), size=readle(lv3_header[0x18:0x1C]))
        lv3_filemeta = RomFSRegion(offset=readle(lv3_header[0x1C:0x20]), size=readle(lv3_header[0x20:0x24]))
        lv3_filedata_offset = readle(lv3_header[0x24:0x28])
        self.data_offset = lv3_offset + lv3_filedata_offset

        # verify lv3 header
        if lv3_header_size != ROMFS_LV3_HEADER_SIZE:
            raise InvalidRomFSHeaderError('Length in RomFS Lv3 header is not 0x28')
        if lv3_dirhash.offset < lv3_header_size:
            raise InvalidRomFSHeaderError('Directory Hash offset is before the end of the Lv3 header')
        if lv3_dirmeta.offset < lv3_dirhash.offset + lv3_dirhash.size:
            raise InvalidRomFSHeaderError('Directory Metadata offset is before the end of the Directory Hash region')
        if lv3_filehash.offset < lv3_dirmeta.offset + lv3_dirmeta.size:
            raise InvalidRomFSHeaderError('File Hash offset is before the end of the Directory Metadata region')
        if lv3_filemeta.offset < lv3_filehash.offset + lv3_filehash.size:
            raise InvalidRomFSHeaderError('File Metadata offset is before the end of the File Hash region')
        if lv3_filedata_offset < lv3_filemeta.offset + lv3_filemeta.size:
            raise InvalidRomFSHeaderError('File Data offset is before the end of the File Metadata region')

        # get entries from dirmeta and filemeta
        def iterate_dir(out: dict, raw: bytes, current_path: str):
            first_child_dir = readle(raw[0x8:0xC])
            first_file = readle(raw[0xC:0x10])

            out['type'] = 'dir'
            out['contents'] = {}

            # iterate through all child directories
            if first_child_dir != 0xFFFFFFFF:
                self._file.seek(self._start + lv3_offset + lv3_dirmeta.offset + first_child_dir)
                while True:
                    child_dir_meta = self._file.read(0x18)
                    next_sibling_dir = readle(child_dir_meta[0x4:0x8])
                    child_dir_name = self._file.read(readle(child_dir_meta[0x14:0x18])).decode('utf-16le')
                    child_dir_name_meta = child_dir_name.lower() if case_insensitive else child_dir_name
                    if child_dir_name_meta in out['contents']:
                        print(f'WARNING: Dirname collision! {current_path}{child_dir_name}')
                    out['contents'][child_dir_name_meta] = {'name': child_dir_name}

                    iterate_dir(out['contents'][child_dir_name_meta], child_dir_meta,
                                f'{current_path}{child_dir_name}/')
                    if next_sibling_dir == 0xFFFFFFFF:
                        break
                    self._file.seek(self._start + lv3_offset + lv3_dirmeta.offset + next_sibling_dir)

            if first_file != 0xFFFFFFFF:
                self._file.seek(self._start + lv3_offset + lv3_filemeta.offset + first_file)
                while True:
                    child_file_meta = self._file.read(0x20)
                    next_sibling_file = readle(child_file_meta[0x4:0x8])
                    child_file_offset = readle(child_file_meta[0x8:0x10])
                    child_file_size = readle(child_file_meta[0x10:0x18])
                    child_file_name = self._file.read(readle(child_file_meta[0x1C:0x20])).decode('utf-16le')
                    child_file_name_meta = child_file_name.lower() if self.case_insensitive else child_file_name
                    if child_file_name_meta in out['contents']:
                        print(f'WARNING: Filename collision! {current_path}{child_file_name}')
                    out['contents'][child_file_name_meta] = {'name': child_file_name, 'type': 'file',
                                                             'offset': child_file_offset, 'size': child_file_size}

                    self.total_size += child_file_size
                    if next_sibling_file == 0xFFFFFFFF:
                        break
                    self._file.seek(self._start + lv3_offset + lv3_filemeta.offset + next_sibling_file)

        self._tree_root = {'name': 'ROOT'}
        self.total_size = 0
        self._file.seek(self._start + lv3_offset + lv3_dirmeta.offset)
        iterate_dir(self._tree_root, self._file.read(0x18), '/')

    @overload
    def open(self, path: str, encoding: str, errors: 'Optional[str]' = None,
             newline: 'Optional[str]' = None) -> TextIOWrapper: ...

    @overload
    def open(self, path: str, encoding: None = None, errors: 'Optional[str]' = None,
             newline: 'Optional[str]' = None) -> SubsectionIO: ...

    def open(self, path, encoding=None, errors=None, newline=None):
        """
        Open a file in the RomFS for reading.

        The file opens in binary mode by default, unless `encoding` is specified.

        :param path: Path to a file within the RomFS.
        :param encoding: The name of the encoding used to decode. Specifying this opens the file in text mode.
        :param errors: The error setting of the decoder.
        :param newline: Controls how newlines are handled in text mode. This is passed to :class:`io.TextIOWrapper`.
        :return: A :class:`~.SubsectionIO` object for bytes, or :class:`io.TextIOWrapper` for text.
        :raises RomFSIsADirectoryError: If the item is a directory.
        """
        file_info = self.get_info_from_path(path)
        if not isinstance(file_info, RomFSFileEntry):
            raise RomFSIsADirectoryError(path)
        f = SubsectionIO(self._file, self._start + self.data_offset + file_info.offset, file_info.size)
        if encoding is not None:
            f = TextIOWrapper(f, encoding, errors, newline)
        return f

    def get_info_from_path(self, path: str) -> 'Union[RomFSDirectoryEntry, RomFSFileEntry]':
        """
        Get a directory or file entry.

        :param path: Path to a file or directory within the RomFS.
        :return: A :class:`RomFSFileEntry` or :class:`RomFSDirectoryEntry`.
        :raises RomFSFileNotFoundError: If the item doesn't exist.
        """
        curr = self._tree_root
        if self.case_insensitive:
            path = path.lower()
        if path[0] == '/':
            path = path[1:]
        for part in path.split('/'):
            if part == '':
                break
            try:
                # noinspection PyTypeChecker
                curr = curr['contents'][part]
            except KeyError:
                raise RomFSFileNotFoundError(path)
        if curr['type'] == 'dir':
            contents = (k['name'] for k in curr['contents'].values())
            return RomFSDirectoryEntry(name=curr['name'], type='dir', contents=(*contents,))
        elif curr['type'] == 'file':
            return RomFSFileEntry(name=curr['name'], type='file', offset=curr['offset'], size=curr['size'])
