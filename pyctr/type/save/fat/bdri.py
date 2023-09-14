# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from typing import TYPE_CHECKING

from fs.base import FS

from .base import InnerFATBase
from .common import (InnerFATError, InnerFATHeader, FSInfo, DirEntryBDRI, DirEntryBDRIStruct, FileEntryBDRI,
                     FileEntryBDRIStruct, FATEntryStruct, iterate_fat)
from ....fileio import SubsectionIO

if TYPE_CHECKING:
    from typing import BinaryIO, Union

    from ..common import PartitionContainerBase


class InnerFATBDRI(InnerFATBase):
    """
    Loads an Inner FAT for title databases (DIFF), including ``title.db`` and ``ticket.db``.

    :param fs_file: File-like object for the Inner FAT.
    """

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
