# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from typing import TYPE_CHECKING

from fs.base import FS
from fs.subfs import SubFS
from fs.enums import ResourceType
from fs.info import Info
from fs import errors

from ...base import TypeReaderBase
from ....fileio import SubsectionIO
from .common import (InnerFATError, InnerFATFileNotInitializedError, InnerFATHeader, FSInfo, DirEntryBDRI,
                     DirEntryBDRIStruct, FileEntryBDRI, FileEntryBDRIStruct, FATEntryStruct, iterate_fat,
                     InnerFATOpenFile)

if TYPE_CHECKING:
    from typing import BinaryIO, Optional, Collection, Union, Tuple, Iterator, List

    from fs.permissions import Permissions

    from ..common import PartitionContainerBase


class InnerFATBDRI(TypeReaderBase, FS):
    """
    Loads an Inner FAT for title databases (DIFF), including ``title.db`` and ``ticket.db``.

    :param fs_file: File-like object for the Inner FAT.
    """

    def __init__(self, fs_file: 'BinaryIO', *, closefd: bool = False, container: 'PartitionContainerBase' = None):
        super().__init__(fs_file, closefd=closefd)
        FS.__init__(self)
        self.case_insensitive = True
        self._container = container

        preheader = self._file.read(8)

        title_dbs = {b'NANDIDB\0', b'NANDTDB\0', b'TEMPIDB\0', b'TEMPTDB\0'}
        if preheader in title_dbs:
            bdri_offset = 0x80
        elif preheader == b'TICK\1\0\0\0':
            bdri_offset = 0x10
        else:
            raise InnerFATError(f'unknown title database magic {preheader!r}')

        self._file.seek(bdri_offset + self._start)
        header = InnerFATHeader.load(self._file)
        if header.magic != b'BDRI':
            raise InnerFATError(f'expected {b"BDRI"!r}, got {header.magic!r}')

        self._file.seek(header.fs_info_offset + bdri_offset + self._start)
        self._fs_info = FSInfo.load(self._file)

        self._fat_io = SubsectionIO(self._file,
                                    self._fs_info.file_allocation_table_offset + bdri_offset + self._start,
                                    ((self._fs_info.file_allocation_table_entry_count + 1) * FATEntryStruct.size)
                                    + bdri_offset + self._start)

        self._fs_data_file = SubsectionIO(self._file,
                                          self._fs_info.data_region_offset + bdri_offset + self._start,
                                          (self._fs_info.data_region_block_count
                                          * self._fs_info.data_region_block_size) + bdri_offset + self._start)

        dir_table_io = SubsectionIO(self._fs_data_file,
                                    self._fs_info.directory_entry_table_starting_block_index
                                    * self._fs_info.data_region_block_size,
                                    self._fs_info.directory_entry_table_block_count
                                    * self._fs_info.data_region_block_size)

        file_table_io = SubsectionIO(self._fs_data_file,
                                     self._fs_info.file_entry_table_starting_block_index
                                     * self._fs_info.data_region_block_size,
                                     self._fs_info.file_entry_table_block_count
                                     * self._fs_info.data_region_block_size)

        def iterate_dir(
                entry: 'DirEntryBDRI',
                out: dict,
                file_table: 'BinaryIO',
                fat: 'BinaryIO'
        ):
            out['type'] = 'dir'
            out['contents'] = {}

            if entry.first_file_index:
                file_table.seek(entry.first_file_index * FileEntryBDRIStruct.size)
                while True:
                    file = FileEntryBDRI.load(file_table)
                    if file.first_block_index != 0x80000000:
                        data_indexes = iterate_fat(file.first_block_index + 1, fat)
                    else:
                        data_indexes = []
                    name = f'{file.title_id:016x}'
                    file_entry = {'name': name,
                                  'type': 'file',
                                  'firstblock': file.first_block_index,
                                  'dataindexes': data_indexes,
                                  'size': file.size}
                    out['contents'][name] = file_entry

                    if not file.next_sibling_file_index:
                        break
                    file_table.seek(file.next_sibling_file_index * FileEntryBDRIStruct.size)

        # first one is always a dummy entry, so we skip ahead the second which is always root
        dir_table_io.seek(DirEntryBDRIStruct.size)
        root_entry = DirEntryBDRI.load(dir_table_io)
        self._tree_root = {'name': ''}
        iterate_dir(root_entry, self._tree_root, file_table_io, self._fat_io)

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

    def getmeta(self, namespace: str = 'standard') -> 'dict[str, Union[bool, str, int]]':
        if namespace != 'standard':
            return {}

        return {'case_insensitive': self.case_insensitive,
                'invalid_path_chars': '\0',
                'max_path_length': 16,
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

