# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from struct import iter_unpack
from typing import TYPE_CHECKING

from .base import InnerFATBase
from .common import (InnerFATError, InnerFATHeader, FSInfo, DirEntryDummySAVEVSXEStruct, DirEntryDummySAVEVSXE,
                     DirEntrySAVEVSXE, FileEntrySAVE, DirEntrySAVEVSXEStruct, FileEntrySAVEStruct,
                     FileEntryDummySAVEVSXEStruct, FileEntryDummySAVEVSXE, FATEntryStruct, get_bucket)
from ....fileio import SubsectionIO

if TYPE_CHECKING:
    from typing import BinaryIO, Optional, Union, Dict

    from ..common import PartitionContainerBase


class InnerFATSAVE(InnerFATBase):
    """
    Loads an Inner FAT for savegames (DISA).

    :param fs_file: File-like object for the Inner FAT.
    :param fs_data_file: File-like object for the data region, only if it's in Partition B of the DISA wrapper.
    """

    _file_type_nt = FileEntrySAVE
    _file_type_struct = FileEntrySAVEStruct
    _dir_type_nt = DirEntrySAVEVSXE
    _dir_type_struct = DirEntrySAVEVSXEStruct

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

        self._dir_hash_table = [x[0] for x in iter_unpack('<I', self._dir_hash_table_io.read())]
        self._file_hash_table = [x[0] for x in iter_unpack('<I', self._file_hash_table_io.read())]

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
            self._always_close_data_file = True

            self._dir_table_io = SubsectionIO(self._fs_data_file,
                                              self._fs_info.directory_entry_table_starting_block_index
                                              * self._fs_info.data_region_block_size
                                              + self._start,
                                              self._fs_info.directory_entry_table_block_count
                                              * self._fs_info.data_region_block_size
                                              + self._start)

            self._file_table_io = SubsectionIO(self._fs_data_file,
                                               self._fs_info.file_entry_table_starting_block_index
                                               * self._fs_info.data_region_block_size
                                               + self._start,
                                               self._fs_info.file_entry_table_block_count
                                               * self._fs_info.data_region_block_size
                                               + self._start)
        else:  # savegames with duplicate data = false
            if fs_data_file is None:
                raise InnerFATError('fs_data_file is None but is required for this save '
                                    '(hint: if loading from a DISA, provide both partitions)')
            self._fs_data_file = fs_data_file
            self._always_close_data_file = False

            self._dir_table_io = SubsectionIO(self._file,
                                              self._fs_info.directory_entry_table_offset + self._start,
                                              ((self._fs_info.maximum_directory_count + 2)
                                               * self._dir_type_struct.size) + self._start)
            self._file_table_io = SubsectionIO(self._file,
                                               self._fs_info.file_entry_table_offset + self._start,
                                               ((self._fs_info.maximum_file_count + 1) * FileEntrySAVEStruct.size)
                                               + self._start)

        self._dummy_dirs = {}
        idx = 0
        while True:
            entry = DirEntryDummySAVEVSXE.load(self._dir_table_io)
            self._dummy_dirs[idx] = entry
            idx = entry.next_dummy_entry
            if not idx:
                break
            self._dir_table_io.seek(idx * DirEntryDummySAVEVSXEStruct.size)

        self._dummy_files = {}
        idx = 0
        while True:
            entry = FileEntryDummySAVEVSXE.load(self._file_table_io)
            self._dummy_files[idx] = entry
            idx = entry.next_dummy_entry
            if not idx:
                break
            self._file_table_io.seek(idx * FileEntryDummySAVEVSXEStruct.size)

        self._dir_table: 'Dict[int, DirEntrySAVEVSXE]' = {}
        self._file_table: 'Dict[int, FileEntrySAVE]' = {}
        self._fat_indexes = {}

        self._iterate_dir(1)

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

    _get_bucket = staticmethod(get_bucket)
