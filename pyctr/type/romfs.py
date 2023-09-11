# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

"""Module for interacting with Read-only Filesystem (RomFS) files."""
import logging
from io import BytesIO
from struct import Struct
from typing import TYPE_CHECKING, NamedTuple, overload
from warnings import warn

from fs.base import FS
from fs.subfs import SubFS
from fs.info import Info
from fs.enums import ResourceType
from fs import errors

from .base import TypeReaderBase
from ..common import PyCTRError
from ..fileio import SubsectionIO
from ..util import readle, roundup

if TYPE_CHECKING:  # pragma: no cover
    from typing import IO, BinaryIO, Optional, Tuple, Union, List, Iterator
    from ..common import FilePathOrObject
    from collections.abc import Collection

__all__ = ['IVFC_HEADER_SIZE', 'IVFC_ROMFS_MAGIC_NUM', 'ROMFS_LV3_HEADER_SIZE', 'RomFSError', 'InvalidIVFCError',
           'InvalidRomFSHeaderError', 'RomFSEntryError', 'RomFSFileNotFoundError', 'RomFSReader']

logger = logging.getLogger(__name__)

IVFC_HEADER_SIZE = 0x5C
IVFC_ROMFS_MAGIC_NUM = 0x10000
ROMFS_LV3_HEADER_SIZE = 0x28

Lv3HeaderStruct = Struct('<IIIIIIIIII')
# these do not include the filename
DirectoryEntryStruct = Struct('<IIIIII')
FileEntryStruct = Struct('<IIQQII')

# used in RomFSReader.open compatibility
_encodings = ['ascii', 'big5', 'big5hkscs', 'cp037', 'cp273', 'cp424', 'cp437', 'cp500', 'cp720', 'cp737', 'cp775',
              'cp850', 'cp852', 'cp855', 'cp856', 'cp857', 'cp858', 'cp860', 'cp861', 'cp862', 'cp863', 'cp864',
              'cp865', 'cp866', 'cp869', 'cp874', 'cp875', 'cp932', 'cp949', 'cp950', 'cp1006', 'cp1026', 'cp1125',
              'cp1140', 'cp1250', 'cp1251', 'cp1252', 'cp1253', 'cp1254', 'cp1255', 'cp1256', 'cp1257', 'cp1258',
              'euc_jp', 'euc_jis_2004', 'euc_jisx0213', 'euc_kr', 'gb2312', 'gbk', 'gb18030', 'hz', 'iso2022_jp',
              'iso2022_jp_1', 'iso2022_jp_2', 'iso2022_jp_2004', 'iso2022_jp_3', 'iso2022_jp_ext', 'iso2022_kr',
              'latin_1', 'iso8859_2', 'iso8859_3', 'iso8859_4', 'iso8859_5', 'iso8859_6', 'iso8859_7', 'iso8859_8',
              'iso8859_9', 'iso8859_10', 'iso8859_11', 'iso8859_13', 'iso8859_14', 'iso8859_15', 'iso8859_16', 'johab',
              'koi8_r', 'koi8_t', 'koi8_u', 'kz1048', 'mac_cyrillic', 'mac_greek', 'mac_iceland', 'mac_latin2',
              'mac_roman', 'mac_turkish', 'ptcp154', 'shift_jis', 'shift_jis_2004', 'shift_jisx0213', 'utf_32',
              'utf_32_be', 'utf_32_le', 'utf_16', 'utf_16_be', 'utf_16_le', 'utf_7', 'utf_8', 'utf_8_sig']



class RomFSError(PyCTRError):
    """Generic exception for RomFS operations."""


class InvalidIVFCError(RomFSError):
    """Invalid IVFC header exception."""


class InvalidRomFSHeaderError(RomFSError):
    """Invalid RomFS Level 3 header."""


class RomFSEntryError(RomFSError):
    """Error with RomFS Directory or File entry."""


class RomFSFileNotFoundError(RomFSEntryError, errors.ResourceNotFound):
    """Invalid file path in RomFS Level 3."""


class RomFSIsADirectoryError(RomFSEntryError, errors.FileExpected):
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


class RomFSLv3Header(NamedTuple):
    header_size: int
    dirhash: RomFSRegion
    dirmeta: RomFSRegion
    filehash: RomFSRegion
    filemeta: RomFSRegion
    filedata_offset: int

    @classmethod
    def from_bytes(cls, data: bytes):
        if len(data) != 0x28:
            raise InvalidRomFSHeaderError(f'Lv3 is not 0x28 bytes (given {len(data):#x})')
        header_raw = Lv3HeaderStruct.unpack(data)
        return cls(header_size=header_raw[0],
                   dirhash=RomFSRegion(offset=header_raw[1], size=header_raw[2]),
                   dirmeta=RomFSRegion(offset=header_raw[3], size=header_raw[4]),
                   filehash=RomFSRegion(offset=header_raw[5], size=header_raw[6]),
                   filemeta=RomFSRegion(offset=header_raw[7], size=header_raw[8]),
                   filedata_offset=header_raw[9])


class RomFSReader(TypeReaderBase, FS):
    """
    Reads the contents of the RomFS, found inside NCCH containers.

    The RomFS found inside an NCCH is wrapped in an IVFC hash-tree container. This class only supports Level 3, which
    contains the actual files.

    :param file: A file path or a file-like object with the RomFS data.
    :param case_insensitive: Use case-insensitive paths.
    :param closefd: Close the underlying file object when closed. Defaults to `True` for file paths, and `False` for
        file-like objects.
    :param open_compatibility_mode: Changes the behavior of :meth:`open` to behave as it did before pyctr 0.8.0.
        Read its documentation for details.
    """

    __slots__ = ('_tree_root', 'case_insensitive', 'data_offset', 'lv3_offset', 'total_size')

    def __init__(self, file: 'FilePathOrObject', case_insensitive: bool = False, *,
                 fs: 'Optional[FS]' = None, closefd: bool = None, open_compatibility_mode: bool = True):
        super().__init__(file, fs=fs, closefd=closefd)
        self.case_insensitive = case_insensitive
        self.open_compatibility_mode = open_compatibility_mode

        lv3_offset = self._file.tell()
        # this reads the full amount that an ivfc header might be,
        # but this could also be a lv3 header which is only 0x28 bytes
        # this is just to reduce the amount of read calls
        header = self._file.read(IVFC_HEADER_SIZE)
        magic = header[0:4]

        # detect ivfc and get the lv3 offset
        if magic == b'IVFC':
            ivfc_magic_num = readle(header[0x4:0x8])
            if ivfc_magic_num != IVFC_ROMFS_MAGIC_NUM:
                raise InvalidIVFCError(f'IVFC magic number is invalid '
                                       f'({ivfc_magic_num:#X} instead of {IVFC_ROMFS_MAGIC_NUM:#X})')
            master_hash_size = readle(header[0x8:0xC])
            lv3_block_size = readle(header[0x4C:0x50])
            lv3_hash_block_size = 1 << lv3_block_size
            lv3_offset += roundup(0x60 + master_hash_size, lv3_hash_block_size)
            self._file.seek(self._start + lv3_offset)
            lv3_header = self._file.read(ROMFS_LV3_HEADER_SIZE)
        else:
            lv3_header = header[0:ROMFS_LV3_HEADER_SIZE]

        self.lv3_offset = lv3_offset

        # get offsets and sizes from lv3 header
        lv3 = RomFSLv3Header.from_bytes(lv3_header[0:0x28])
        self.data_offset = lv3_offset + lv3.filedata_offset

        # verify lv3 header
        if lv3.header_size != ROMFS_LV3_HEADER_SIZE:
            raise InvalidRomFSHeaderError('Length in RomFS Lv3 header is not 0x28')
        if lv3.dirhash.offset < lv3.header_size:
            raise InvalidRomFSHeaderError('Directory Hash offset is before the end of the Lv3 header')
        if lv3.dirmeta.offset < lv3.dirhash.offset + lv3.dirhash.size:
            raise InvalidRomFSHeaderError('Directory Metadata offset is before the end of the Directory Hash region')
        if lv3.filehash.offset < lv3.dirmeta.offset + lv3.dirmeta.size:
            raise InvalidRomFSHeaderError('File Hash offset is before the end of the Directory Metadata region')
        if lv3.filemeta.offset < lv3.filehash.offset + lv3.filehash.size:
            raise InvalidRomFSHeaderError('File Metadata offset is before the end of the File Hash region')
        if lv3.filedata_offset < lv3.filemeta.offset + lv3.filemeta.size:
            raise InvalidRomFSHeaderError('File Data offset is before the end of the File Metadata region')

        # get entries from dirmeta and filemeta
        def iterate_dir(out: dict, raw: bytes, current_path: str, dirmeta: 'BinaryIO', filemeta: 'BinaryIO'):
            first_child_dir = readle(raw[0x8:0xC])
            first_file = readle(raw[0xC:0x10])

            out['type'] = 'dir'
            out['contents'] = {}

            # iterate through all child directories
            if first_child_dir != 0xFFFFFFFF:
                dirmeta.seek(first_child_dir)
                while True:
                    child_dir_meta = dirmeta.read(0x18)
                    next_sibling_dir = readle(child_dir_meta[0x4:0x8])
                    child_dir_name = dirmeta.read(readle(child_dir_meta[0x14:0x18])).decode('utf-16le')
                    child_dir_name_meta = child_dir_name.lower() if case_insensitive else child_dir_name
                    if child_dir_name_meta in out['contents']:
                        logger.warning(f'Dirname collision: {current_path}{child_dir_name}')
                    out['contents'][child_dir_name_meta] = {'name': child_dir_name}

                    iterate_dir(out['contents'][child_dir_name_meta], child_dir_meta,
                                f'{current_path}{child_dir_name}/', dirmeta, filemeta)
                    if next_sibling_dir == 0xFFFFFFFF:
                        break
                    dirmeta.seek(next_sibling_dir)

            if first_file != 0xFFFFFFFF:
                filemeta.seek(first_file)
                while True:
                    child_file_meta = filemeta.read(0x20)
                    next_sibling_file = readle(child_file_meta[0x4:0x8])
                    child_file_offset = readle(child_file_meta[0x8:0x10])
                    child_file_size = readle(child_file_meta[0x10:0x18])
                    child_file_name = filemeta.read(readle(child_file_meta[0x1C:0x20])).decode('utf-16le')
                    child_file_name_meta = child_file_name.lower() if self.case_insensitive else child_file_name
                    if child_file_name_meta in out['contents']:
                        logger.warning(f'Filename collision! {current_path}{child_file_name}')
                    out['contents'][child_file_name_meta] = {'name': child_file_name, 'type': 'file',
                                                             'offset': child_file_offset, 'size': child_file_size}

                    self.total_size += child_file_size
                    if next_sibling_file == 0xFFFFFFFF:
                        break
                    filemeta.seek(next_sibling_file)

        self._tree_root = {'name': 'ROOT'}
        self.total_size = 0

        self._file.seek(self._start + lv3_offset + lv3.dirmeta.offset)
        dirmeta = BytesIO(self._file.read(lv3.dirmeta.size))
        self._file.seek(self._start + lv3_offset + lv3.filemeta.offset)
        filemeta = BytesIO(self._file.read(lv3.filemeta.size))

        iterate_dir(self._tree_root, dirmeta.read(0x18), '/', dirmeta, filemeta)

    def _get_raw_info(self, path: str):
        curr = self._tree_root
        if path == '.':
            return curr
        if self.case_insensitive:
            path = path.lower()
        if path[0:2] == './':
            path = path[2:]
        elif path[0] == '/':
            path = path[1:]
        for part in path.split('/'):
            if part == '':
                break
            try:
                # noinspection PyTypeChecker
                curr = curr['contents'][part]
            except KeyError:
                raise RomFSFileNotFoundError(path)

        return curr

    def _gen_info(self, c: dict) -> Info:
        is_dir = c['type'] == 'dir'
        info = {'basic': {'name': c['name'],
                          'is_dir': is_dir},
                'details': {'size': 0 if is_dir else c['size'],
                            'type': ResourceType.directory if is_dir else ResourceType.file}}
        if not is_dir:
            info['rawfs'] = {'offset': c['offset']}

        return Info(info)

    def getinfo(self, path: str, namespaces: 'Optional[Collection[str]]' = ()) -> Info:
        curr = self._get_raw_info(path)
        return self._gen_info(curr)

    def getmeta(self, namespace: str = 'standard') -> 'dict[str, Union[bool, str, int]]':
        if namespace != 'standard':
            return {}

        return {'case_insensitive': self.case_insensitive,
                'invalid_path_chars': '\0',
                'max_path_length': None,
                'max_sys_path_length': None,
                'network': False,
                'read_only': True,
                'supports_rename': False}

    def listdir(self, path: str) -> 'List[str]':
        file_info_raw = self._get_raw_info(path)
        if file_info_raw['type'] != 'dir':
            raise errors.DirectoryExpected
        return [x['name'] for x in file_info_raw['contents'].values()]

    def makedir(
        self,
        path: str,
        permissions: 'Optional[Permissions]' = None,
        recreate: bool = False,
    ) -> 'SubFS[FS]':
        raise errors.ResourceReadOnly(path)

    def openbin(self, path, mode='r', buffering=-1, **options):
        file_info = self.getinfo(path)
        if file_info.is_dir:
            raise RomFSIsADirectoryError(path)
        if 'w' in mode or '+' in mode or 'a' in mode:
            raise errors.ResourceReadOnly(path)
        f = SubsectionIO(self._file, self._start + self.data_offset + file_info.get('rawfs', 'offset'), file_info.size)
        self._open_files.add(f)
        return f

    @overload
    def open(
        self,
        path,
        mode: str = 'r',
        buffering: int = -1,
        encoding: 'Optional[str]' = None,
        errors: 'Optional[str]' = None,
        newline: str = '',
        **options
    ) -> 'IO':
        ...

    # compatibility function
    def open(
        self,
        path: str,
        mode: str = '__unset__',
        *compat_args,
        **options
    ) -> 'IO':
        """
        .. warning::

            By default, for compatibility reasons, this function works differently than the normal FS open method.
            Files are opened in binary mode by default and ``mode`` accepts an encoding.
            This can be toggled off when creating the RomFSReader by passing ``open_compatibility_mode=False``.
            This compatibility layer will be removed in a future release.
        """
        if self.open_compatibility_mode:
            if mode.replace('-', '_') in _encodings:
                warn('RomFSReader.open function signature has changed to match that of fs.base.FS.open, '
                     'please change to open(path, encoding="your-encoding")', DeprecationWarning)
                # this needs to be compatible with older code that didn't expect a mode argumemnt here
                # noinspection PyTypeChecker
                real_errors = options.get('errors', None)
                if not real_errors and len(compat_args) >= 1:
                    real_errors = compat_args[0]
                real_newline = options.get('newline', '')
                if not real_newline and len(compat_args) >= 2:
                    real_newline = compat_args[1]
                return super().open(path,
                                    mode='rt',
                                    buffering=-1,
                                    encoding=mode,
                                    errors=real_errors,
                                    newline=real_newline)
            elif mode == '__unset__':
                real_encoding = options.get('encoding', None)
                if not real_encoding:
                    warn('no mode or encoding specified so opening in binary mode, future versions will open '
                         'in text mode by default to match function signature of fs.base.FS.open; '
                         'either specify mode="rb", use openbin, or specify an encoding', DeprecationWarning)
                    return super().open(path, 'rb', buffering=-1, *compat_args, **options)
                else:
                    # no problem here since this will continue to work
                    return super().open(path, mode='rt', *compat_args, **options)
        else:
            if mode == '__unset__':
                # the real default
                mode = 'r'
        return super().open(path, mode, *compat_args, **options)

    def scandir(
        self,
        path: str,
        namespaces: 'Optional[Collection[str]]' = None,
        page: 'Optional[Tuple[int, int]]' = None,
    ) -> 'Iterator[Info]':
        curr = self._get_raw_info(path)
        if curr['type'] != 'dir':
            raise errors.DirectoryExpected(path)

        for c in curr['contents'].values():
            yield self._gen_info(c)

    def remove(self, path: str):
        raise errors.ResourceReadOnly(path)

    def removedir(self, path: str):
        raise errors.ResourceReadOnly(path)

    def setinfo(self, path: str, info: dict):
        raise errors.ResourceReadOnly(path)

    def get_info_from_path(self, path: str):
        """
        .. deprecated:: 0.8.0
            Use :meth:`getinfo`, :meth:`listdir`, or :meth:`scandir` instead.

        :param path:
        :return:
        """
        warn('RomFSReader.get_info_from_path should be replaced with getinfo, listdir, or scandir',
             DeprecationWarning)
        file_info = self.getinfo(path)
        if file_info.is_dir:
            return RomFSDirectoryEntry(file_info.name, 'dir', tuple(self.listdir(path)))
        else:
            return RomFSFileEntry(file_info.name, 'file', file_info.get('rawfs', 'offset'), file_info.size)
