# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from typing import TYPE_CHECKING

from .base import InnerFATBase
from .common import (InnerFATError, InnerFATHeader, FSInfo, DirEntrySAVEVSXE, FileEntrySAVE, DirEntrySAVEVSXEStruct,
                     FileEntrySAVEStruct, FATEntryStruct, iterate_fat, get_bucket)
from ....fileio import SubsectionIO

if TYPE_CHECKING:
    from typing import BinaryIO, Optional, Union

    from ..common import PartitionContainerBase


class InnerFATSAVE(InnerFATBase):
    """
    Loads an Inner FAT for savegames (DISA).

    :param fs_file: File-like object for the Inner FAT.
    :param fs_data_file: File-like object for the data region, only if it's in Partition B of the DISA wrapper.
    """
    def __init__(self, fs_file: 'BinaryIO', fs_data_file: 'Optional[BinaryIO]' = None, *,
                 closefd: bool = False, case_insensitive: bool = False, container: 'PartitionContainerBase' = None):
        super().__init__(fs_file, closefd=closefd, container=container, case_insensitive=case_insensitive)

        if case_insensitive:
            raise NotImplementedError('case insensitive is not supported yet')

        header = InnerFATHeader.load(self._file)
        if header.magic != b'SAVE':
            raise InnerFATError(f'expected {b"SAVE"!r}, got {header.magic!r}')

        self._seek(header.fs_info_offset)
        self._fs_info = FSInfo.load(self._file)

        self._dir_hash_table_io = SubsectionIO(self._file,
                                               self._fs_info.directory_hash_table_offset + self._start,
                                               (self._fs_info.directory_hash_table_bucket_count * 4) + self._start)

        self._file_hash_table_io = SubsectionIO(self._file,
                                                self._fs_info.file_hash_table_offset + self._start,
                                                (self._fs_info.file_hash_table_bucket_count * 4) + self._start)

        self._fat_io = SubsectionIO(self._file,
                                    self._fs_info.file_allocation_table_offset + self._start,
                                    ((self._fs_info.file_allocation_table_entry_count + 1) * FATEntryStruct.size)
                                    + self._start)

        if self._fs_info.data_region_offset:  # savegames with duplicate data = true
            self._fs_data_file = SubsectionIO(self._file,
                                              self._fs_info.data_region_offset + self._start,
                                              self._fs_info.data_region_block_count
                                              * self._fs_info.data_region_block_size
                                              + self._start)

            dir_table_io = SubsectionIO(self._fs_data_file,
                                        self._fs_info.directory_entry_table_starting_block_index
                                        * self._fs_info.data_region_block_size
                                        + self._start,
                                        self._fs_info.directory_entry_table_block_count
                                        * self._fs_info.data_region_block_size
                                        + self._start)

            file_table_io = SubsectionIO(self._fs_data_file,
                                         self._fs_info.file_entry_table_starting_block_index
                                         * self._fs_info.data_region_block_size
                                         + self._start,
                                         self._fs_info.file_entry_table_block_count
                                         * self._fs_info.data_region_block_size
                                         + self._start)
        else:  # savegames with duplicate data = false
            self._fs_data_file = fs_data_file

            dir_table_io = SubsectionIO(self._file,
                                        self._fs_info.directory_entry_table_offset + self._start,
                                        ((self._fs_info.maximum_directory_count + 2) * DirEntrySAVEVSXEStruct.size)
                                        + self._start)
            file_table_io = SubsectionIO(self._file,
                                         self._fs_info.file_entry_table_offset + self._start,
                                         ((self._fs_info.maximum_file_count + 1) * FileEntrySAVEStruct.size)
                                         + self._start)

        def iterate_dir(
                entry: 'DirEntrySAVEVSXE',
                out: dict,
                dir_table: 'BinaryIO',
                file_table: 'BinaryIO',
                fat: 'BinaryIO'
        ):
            out['type'] = 'dir'
            out['contents'] = {}
            out['name'] = entry.name

            if entry.first_subdirectory_index:
                dir_table.seek(entry.first_subdirectory_index * DirEntrySAVEVSXEStruct.size)
                while True:
                    subdir = DirEntrySAVEVSXE.load(dir_table)
                    subdir_entry = {'name': subdir.name}
                    out['contents'][subdir.name] = subdir_entry

                    iterate_dir(subdir, subdir_entry, dir_table, file_table, fat)

                    if not subdir.next_sibling_directory_index:
                        break
                    dir_table.seek(subdir.next_sibling_directory_index * DirEntrySAVEVSXEStruct.size)

            if entry.first_file_index:
                idx = entry.first_file_index
                file_table.seek(idx * FileEntrySAVEStruct.size)
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
                    idx = file.next_sibling_file_index
                    file_table.seek(idx * FileEntrySAVEStruct.size)

        # first one is always a dummy entry, so we skip ahead the second which is always root
        dir_table_io.seek(DirEntrySAVEVSXEStruct.size)
        root_entry = DirEntrySAVEVSXE.load(dir_table_io)
        self._tree_root = {'name': root_entry.name}
        iterate_dir(root_entry, self._tree_root, dir_table_io, file_table_io, self._fat_io)

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
