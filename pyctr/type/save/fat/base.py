# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from typing import TYPE_CHECKING

from fs import errors
from fs.base import FS
from fs.enums import ResourceType
from fs.info import Info
from fs.subfs import SubFS

from .common import InnerFATFileNotInitializedError, InnerFATOpenFile, InnerFATError
from ...base import TypeReaderBase

if TYPE_CHECKING:
    from typing import BinaryIO, Optional, Collection, Tuple, Iterator, List

    from fs.permissions import Permissions

    from ..common import PartitionContainerBase
    from .common import FSInfo


class InnerFATBase(TypeReaderBase, FS):

    _fs_data_file: 'BinaryIO'
    _fs_info: 'FSInfo'
    _tree_root: dict
    _fat_io: 'BinaryIO'
    _dir_hash_table_io: 'BinaryIO'
    _file_hash_table_io: 'BinaryIO'

    def __init__(self, fs_file: 'BinaryIO', *, closefd: bool = False, case_insensitive: bool = False,
                 container: 'PartitionContainerBase' = None):
        super().__init__(fs_file, closefd=closefd)
        FS.__init__(self)
        self.case_insensitive = case_insensitive
        self._container = container

        self._fs_file = fs_file

    def close(self):
        if not self.closed:
            super().close()
            FS.close(self)
            if self._closefd:
                self._fs_data_file.close()
                if self._container:
                    self._container.close()

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
                raise errors.ResourceNotFound(path)

        return curr

    def _gen_info(self, c: dict) -> 'Info':
        is_dir = c['type'] == 'dir'
        info = {'basic': {'name': c['name'],
                          'is_dir': is_dir},
                'details': {'size': 0 if is_dir else c['size'],
                            'type': ResourceType.directory if is_dir else ResourceType.file}}
        if not is_dir:
            info['rawfs'] = {'firstblock': c['firstblock'], 'dataindexes': c['dataindexes']}

        return Info(info)

    def getinfo(self, path: str, namespaces: 'Optional[Collection[str]]' = ()) -> Info:
        curr = self._get_raw_info(path)
        return self._gen_info(curr)

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

    def openbin(self, path, mode='r', buffering=-1, **options) -> 'InnerFATOpenFile':
        file_info = self.getinfo(path)
        if file_info.is_dir:
            raise errors.FileExpected(path)
        if 'w' in mode or '+' in mode or 'a' in mode:
            raise errors.ResourceReadOnly(path)

        data_indexes = file_info.get('rawfs', 'dataindexes')
        if not data_indexes:
            raise InnerFATFileNotInitializedError(path)

        fh = InnerFATOpenFile(self._fs_data_file,
                              data_indexes,
                              file_info.size,
                              self._fs_info.data_region_block_size)
        self._open_files.add(fh)
        return fh

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

    def _get_bucket(self, dir_or_file: str, bucket: int) -> int:
        if dir_or_file == 'dir':
            f = self._dir_hash_table_io
        elif dir_or_file == 'file':
            f = self._file_hash_table_io
        else:
            raise InnerFATError('internal pyctr error')

        f.seek(bucket * 4)
        return int.from_bytes(f.read(4), 'little')
