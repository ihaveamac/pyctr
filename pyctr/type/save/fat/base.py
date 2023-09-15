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
from fs.path import parts
from fs.subfs import SubFS

from .common import InnerFATFileNotInitializedError, InnerFATOpenFile, get_bucket, iterate_fat
from ...base import TypeReaderBase

if TYPE_CHECKING:
    from typing import BinaryIO, Optional, Collection, Tuple, Iterator, List, Dict, Union, Type

    from fs.permissions import Permissions

    from ..common import PartitionContainerBase
    from .common import (FSInfo, FileEntrySAVEStruct, FileEntrySAVE, FileEntryBDRI, FileEntryBDRIStruct,
                         DirEntrySAVEVSXEStruct, DirEntrySAVEVSXE, DirEntryBDRIStruct, DirEntryBDRI)

    StructTypes = Union[Type[FileEntrySAVEStruct], Type[FileEntryBDRIStruct], Type[DirEntrySAVEVSXEStruct],
                        Type[DirEntryBDRIStruct]]
    EntryTypes = Union[FileEntrySAVE, FileEntryBDRI, DirEntrySAVEVSXE, DirEntryBDRI]


class InnerFATBase(TypeReaderBase, FS):

    _fs_data_file: 'BinaryIO'
    _fs_info: 'FSInfo'
    _tree_root: dict
    _fat_io: 'BinaryIO'
    _dir_hash_table_io: 'BinaryIO'
    _file_hash_table_io: 'BinaryIO'
    _dir_hash_table: dict
    _file_hash_table: dict
    _dir_hash_io: 'BinaryIO'
    _file_hash_io: 'BinaryIO'
    _dir_table: dict
    _file_table: dict
    _always_close_data_file: bool = False
    _dir_type_nt: 'EntryTypes'
    _dir_type_struct: 'StructTypes'
    _file_type_nt: 'EntryTypes'
    _file_type_struct: 'StructTypes'
    _fat_indexes: 'Dict[int, List[int]]'

    _get_bucket = staticmethod(get_bucket)

    def __init__(self, fs_file: 'BinaryIO', *, closefd: bool = False, case_insensitive: bool = False,
                 container: 'PartitionContainerBase' = None):
        super().__init__(fs_file, closefd=closefd)
        FS.__init__(self)
        self.case_insensitive = case_insensitive
        self._container = container

        self._fs_file = fs_file

    def _iterate_dir(self, idx: int) -> int:
        self._dir_table_io.seek(idx * self._dir_type_struct.size)
        entry = self._dir_type_nt.load(self._dir_table_io)
        self._dir_table[idx] = entry

        if entry.first_subdirectory_index:
            subidx = entry.first_subdirectory_index
            while True:
                subidx = self._iterate_dir(subidx)
                if not subidx:
                    break

        if entry.first_file_index:
            fileidx = entry.first_file_index
            while True:
                self._file_table_io.seek(fileidx * self._file_type_struct.size)
                fileentry = self._file_type_nt.load(self._file_table_io)
                self._file_table[fileidx] = fileentry
                self._fat_indexes[fileidx] = iterate_fat(fileentry.first_block_index + 1, self._fat_io)
                fileidx = fileentry.next_sibling_file_index
                if not fileidx:
                    break

        return entry.next_sibling_directory_index

    def close(self):
        if not self.closed:
            super().close()
            FS.close(self)
            if self._always_close_data_file:
                self._fs_data_file.close()
            if self._closefd:
                self._fs_data_file.close()
                if self._container:
                    self._container.close()

    def _get_entry(self, path: str):
        path_parts = parts(path)
        path_parts[0] = ''  # special case so get_bucket can work on root
        parent_idx = 0
        entry = None
        final_idx = 0
        for idx, part in enumerate(path_parts):  # type: int, str
            dir_bucket = self._get_bucket(part, parent_idx, self._fs_info.directory_hash_table_bucket_count)
            file_bucket = self._get_bucket(part, parent_idx, self._fs_info.file_hash_table_bucket_count)
            dir_entry_idx = None
            file_entry_idx = None
            try:
                dir_entry_idx = self._dir_hash_table[dir_bucket]
            except KeyError:
                pass

            try:
                file_entry_idx = self._file_hash_table[file_bucket]
            except KeyError:
                pass

            if not dir_entry_idx and not file_entry_idx:
                raise errors.ResourceNotFound(path)

            if dir_entry_idx is not None:
                do_continue = True
                while True:
                    entry = None
                    try:
                        entry = self._dir_table[dir_entry_idx]
                    except KeyError:
                        # could be a file
                        do_continue = False
                        break
                    if entry.name == part:
                        final_idx = dir_entry_idx
                        break
                    else:
                        if entry.next_directory_in_same_hash_table_bucket:
                            dir_entry_idx = entry.next_directory_in_same_hash_table_bucket
                        else:
                            # could be a file
                            do_continue = False
                            break
                parent_idx = dir_entry_idx
                if do_continue:
                    continue

            if file_entry_idx is not None:
                while True:
                    try:
                        entry = self._file_table[file_entry_idx]
                    except KeyError:
                        # could be a directory
                        raise errors.ResourceNotFound(path)
                    if entry.name == part:
                        final_idx = file_entry_idx
                        break
                    else:
                        if entry.next_file_in_same_hash_table_bucket:
                            file_entry_idx = entry.next_file_in_same_hash_table_bucket
                        else:
                            # probably doesn't exist then...
                            raise errors.ResourceNotFound(path)

                if idx != len(path_parts) - 1:
                    # wait what? a file detected at a part that isn't the end
                    raise errors.ResourceNotFound(path)

        if not entry:
            raise errors.ResourceNotFound(path)

        return final_idx, entry

    def _gen_info(self, idx: int, entry) -> 'Info':
        if isinstance(entry, self._dir_type_nt):
            info = {'basic': {'name': entry.name,
                              'is_dir': True},
                    'details': {'size': 0,
                                'type': ResourceType.directory},
                    'rawfs': {'index': idx}}
        else:
            info = {'basic': {'name': entry.name,
                              'is_dir': False},
                    'details': {'size': entry.size,
                                'type': ResourceType.file},
                    'rawfs': {'firstblock': entry.first_block_index,
                              'index': idx,
                              'dataindexes': self._fat_indexes[idx]}}
        return Info(info)

    def scandir(
            self,
            path: str,
            namespaces: 'Optional[Collection[str]]' = None,
            page: 'Optional[Tuple[int, int]]' = None
    ) -> 'Iterator[Info]':
        idx, entry = self._get_entry(path)
        if not isinstance(entry, self._dir_type_nt):
            raise errors.DirectoryExpected(path)

        diridx = entry.first_subdirectory_index
        while diridx:
            direntry = self._dir_table[diridx]
            yield self._gen_info(diridx, direntry)
            diridx = direntry.next_sibling_directory_index

        fileidx = entry.first_file_index
        while fileidx:
            fileentry = self._file_table[fileidx]
            yield self._gen_info(fileidx, fileentry)
            fileidx = fileentry.next_sibling_file_index

    def listdir(self, path: str) -> 'List[str]':
        return list(x.name for x in self.scandir(path))

    def getinfo(self, path: str, namespaces: 'Optional[Collection[str]]' = None):
        idx, entry = self._get_entry(path)
        return self._gen_info(idx, entry)

    def openbin(
        self,
        path: str,
        mode: str = 'r',
        buffering: int = -1,
        **options
    ) -> 'BinaryIO':
        if 'w' in mode or '+' in mode or 'a' in mode:
            raise errors.ResourceReadOnly(path)
        info = self.getinfo(path)
        if info.is_dir:
            raise errors.FileExpected(path)

        data_indexes = info.get('rawfs', 'dataindexes')
        if not data_indexes:
            raise InnerFATFileNotInitializedError(path)

        fh = InnerFATOpenFile(self._fs_data_file,
                              data_indexes,
                              info.size,
                              self._fs_info.data_region_block_size)
        self._open_files.add(fh)
        return fh

    def makedir(
        self,
        path: str,
        permissions: 'Optional[Permissions]' = None,
        recreate: bool = False,
    ) -> 'SubFS[FS]':
        raise errors.ResourceReadOnly(path)

    def remove(self, path: str):
        raise errors.ResourceReadOnly(path)

    def removedir(self, path: str):
        raise errors.ResourceReadOnly(path)

    def setinfo(self, path: str, info: dict):
        raise errors.ResourceReadOnly(path)
