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
from .common import (InnerFATError, InnerFATFileNotInitializedError, InnerFATHeader, FSInfo, DirEntrySAVEBDRI,
                     FileEntrySAVE, DirEntrySAVEBDRIStruct, FileEntrySAVEStruct, FATEntryStruct, iterate_fat,
                     InnerFATOpenFile)

if TYPE_CHECKING:
    from typing import BinaryIO, Optional, Collection, Union, Tuple, Iterator, List

    from fs.permissions import Permissions

    from ..common import PartitionContainerBase


class InnerFATSAVE(TypeReaderBase, FS):
    """
    Loads an Inner FAT for savegames (DISA).

    :param fs_file: File-like object for the Inner FAT.
    :param fs_data_file: File-like object for the data region, only if it's in Partition B of the DISA wrapper.
    """
    def __init__(self, fs_file: 'BinaryIO', fs_data_file: 'Optional[BinaryIO]' = None, *,
                 closefd: bool = False, case_insensitive: bool = False, container: 'PartitionContainerBase' = None):
        super().__init__(fs_file, closefd=closefd)
        FS.__init__(self)
        self.case_insensitive = case_insensitive
        self._container = container

        if case_insensitive:
            raise NotImplementedError('case insensitive is not supported yet')

        header = InnerFATHeader.load(self._file)
        if header.magic != b'SAVE':
            raise InnerFATError(f'expected {b"SAVE"!r}, got {header.magic!r}')

        self._file.seek(header.fs_info_offset)
        self._fs_info = FSInfo.load(self._file)

        self._fat_io = SubsectionIO(self._file,
                                    self._fs_info.file_allocation_table_offset,
                                    (self._fs_info.file_allocation_table_entry_count + 1) * FATEntryStruct.size)

        if self._fs_info.data_region_offset:  # savegames with duplicate data = true
            self._fs_data_file = SubsectionIO(self._file,
                                              self._fs_info.data_region_offset,
                                              self._fs_info.data_region_block_count
                                              * self._fs_info.data_region_block_size)

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
        else:  # savegames with duplicate data = false
            self._fs_data_file = fs_data_file

            dir_table_io = SubsectionIO(self._file,
                                        self._fs_info.directory_entry_table_offset,
                                        (self._fs_info.maximum_directory_count + 2) * DirEntrySAVEBDRIStruct.size)
            file_table_io = SubsectionIO(self._file,
                                         self._fs_info.file_entry_table_offset,
                                         (self._fs_info.maximum_file_count + 1) * FileEntrySAVEStruct.size)

        def iterate_dir(
                entry: 'DirEntrySAVEBDRI',
                out: dict,
                dir_table: 'BinaryIO',
                file_table: 'BinaryIO',
                fat: 'BinaryIO'
        ):
            out['type'] = 'dir'
            out['contents'] = {}
            out['name'] = entry.name

            if entry.first_subdirectory_index:
                dir_table.seek(entry.first_subdirectory_index * DirEntrySAVEBDRIStruct.size)
                while True:
                    subdir = DirEntrySAVEBDRI.load(dir_table)
                    subdir_entry = {'name': subdir.name}
                    out['contents'][subdir.name] = subdir_entry

                    iterate_dir(subdir, subdir_entry, dir_table, file_table, fat)

                    if not subdir.next_sibling_directory_index:
                        break
                    dir_table.seek(subdir.next_sibling_directory_index * DirEntrySAVEBDRIStruct.size)

            if entry.first_file_index:
                file_table.seek(entry.first_file_index * FileEntrySAVEStruct.size)
                while True:
                    file = FileEntrySAVE.load(file_table)
                    if file.first_block_index != 0x80000000:
                        data_indexes = iterate_fat(file.first_block_index + 1, fat)
                    else:
                        data_indexes = []
                    file_entry = {'name': file.name,
                                  'type': 'file',
                                  'firstblock': file.first_block_index,
                                  'dataindexes': data_indexes,
                                  'size': file.size}
                    out['contents'][file.name] = file_entry

                    if not file.next_sibling_file_index:
                        break
                    file_table.seek(file.next_sibling_file_index * FileEntrySAVEStruct.size)

        # first one is always a dummy entry, so we skip ahead the second which is always root
        dir_table_io.seek(DirEntrySAVEBDRIStruct.size)
        root_entry = DirEntrySAVEBDRI.load(dir_table_io)
        self._tree_root = {'name': root_entry.name}
        iterate_dir(root_entry, self._tree_root, dir_table_io, file_table_io, self._fat_io)

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
