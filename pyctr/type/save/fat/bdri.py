# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from struct import iter_unpack
from typing import TYPE_CHECKING

from .base import InnerFATBase
from .common import (InnerFATError, InnerFATHeader, FSInfo, DirEntryBDRI, DirEntryBDRIStruct, FileEntryBDRI,
                     FileEntryBDRIStruct, FileEntryDummyBDRI, FileEntryDummyBDRIStruct, FATEntryStruct, get_bucket_tid)
from ....fileio import SubsectionIO

if TYPE_CHECKING:
    from typing import BinaryIO, Union, Dict

    from ..common import PartitionContainerBase


class InnerFATBDRI(InnerFATBase):
    """
    Loads an Inner FAT for title databases (DIFF), including ``title.db`` and ``ticket.db``.

    :param fs_file: File-like object for the Inner FAT.
    """

    _file_type_nt = FileEntryBDRI
    _file_type_struct = FileEntryBDRIStruct
    _dir_type_nt = DirEntryBDRI
    _dir_type_struct = DirEntryBDRIStruct

    def __init__(self, fs_file: 'BinaryIO', *, closefd: bool = False, container: 'PartitionContainerBase' = None):
        super().__init__(fs_file, closefd=closefd, container=container, case_insensitive=True)

        preheader = self._file.read(8)

        title_dbs = {b'NANDIDB\0', b'NANDTDB\0', b'TEMPIDB\0', b'TEMPTDB\0'}
        if preheader in title_dbs:
            bdri_offset = 0x80
        elif preheader == b'TICK\1\0\0\0':
            bdri_offset = 0x10
        else:
            raise InnerFATError(f'unknown title database magic {preheader!r}')

        self._seek(bdri_offset)
        header = InnerFATHeader.load(self._file)
        if header.magic != b'BDRI':
            raise InnerFATError(f'expected {b"BDRI"!r}, got {header.magic!r}')

        self._seek(header.fs_info_offset + bdri_offset)
        self._fs_info = FSInfo.load(self._file)

        self._dir_hash_table_io = SubsectionIO(self._file,
                                               self._fs_info.directory_hash_table_offset + bdri_offset + self._start,
                                               (self._fs_info.directory_hash_table_bucket_count * 4)
                                               + bdri_offset + self._start)

        self._file_hash_table_io = SubsectionIO(self._file,
                                                self._fs_info.file_hash_table_offset + bdri_offset + self._start,
                                                (self._fs_info.file_hash_table_bucket_count * 4)
                                                + bdri_offset + self._start)

        self._dir_hash_table = [x[0] for x in iter_unpack('<I', self._dir_hash_table_io.read())]
        self._file_hash_table = [x[0] for x in iter_unpack('<I', self._file_hash_table_io.read())]

        self._fat_io = SubsectionIO(self._file,
                                    self._fs_info.file_allocation_table_offset + bdri_offset + self._start,
                                    ((self._fs_info.file_allocation_table_entry_count + 1) * FATEntryStruct.size)
                                    + bdri_offset + self._start)

        self._fs_data_file = SubsectionIO(self._file,
                                          self._fs_info.data_region_offset + bdri_offset + self._start,
                                          (self._fs_info.data_region_block_count
                                           * self._fs_info.data_region_block_size) + bdri_offset + self._start)
        self._always_close_data_file = True

        self._dir_table_io = SubsectionIO(self._fs_data_file,
                                          self._fs_info.directory_entry_table_starting_block_index
                                          * self._fs_info.data_region_block_size,
                                          self._fs_info.directory_entry_table_block_count
                                          * self._fs_info.data_region_block_size)

        self._file_table_io = SubsectionIO(self._fs_data_file,
                                           self._fs_info.file_entry_table_starting_block_index
                                           * self._fs_info.data_region_block_size,
                                           self._fs_info.file_entry_table_block_count
                                           * self._fs_info.data_region_block_size)

        self._dummy_files = {}
        idx = 0
        while True:
            entry = FileEntryDummyBDRI.load(self._file_table_io)
            self._dummy_files[idx] = entry
            idx = entry.next_dummy_entry
            if not idx:
                break
            self._file_table_io.seek(idx * FileEntryDummyBDRIStruct.size)

        self._dir_table: 'Dict[int, DirEntryBDRI]' = {}
        self._file_table: 'Dict[int, FileEntryBDRI]' = {}
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

    _get_bucket = staticmethod(get_bucket_tid)
