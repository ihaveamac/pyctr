# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from io import RawIOBase
from struct import Struct
from threading import Lock
from typing import TYPE_CHECKING, NamedTuple

from ....common import PyCTRError, _raise_if_file_closed
from ....fileio import _lock_objects
from ....util import readle

if TYPE_CHECKING:
    from typing import BinaryIO, List
    # this is to trick type checkers into accepting SubsectionIO as a BinaryIO object
    # if you know a better way, let me know
    RawIOBase = BinaryIO


class InnerFATError(PyCTRError):
    """Generic exception for Inner FAT operations."""


class InnerFATFileNotInitializedError(InnerFATError):
    """The file was created, but has no data."""


InnerFATHeaderStruct = Struct('<4s I I I I')


class InnerFATHeader(NamedTuple):
    magic: bytes
    version: int

    fs_info_offset: int
    fs_image_size_blocks: int
    fs_image_block_size: int

    @classmethod
    def from_bytes(cls, data: bytes):
        return cls(*InnerFATHeaderStruct.unpack(data))

    @classmethod
    def load(cls, fp: 'BinaryIO'):
        return cls.from_bytes(fp.read(InnerFATHeaderStruct.size))


class FSInfo(NamedTuple):
    data_region_block_size: int

    directory_hash_table_offset: int
    directory_hash_table_bucket_count: int

    file_hash_table_offset: int
    file_hash_table_bucket_count: int

    file_allocation_table_offset: int
    file_allocation_table_entry_count: int

    data_region_offset: int
    data_region_block_count: int

    directory_entry_table_offset: int  # savegames with duplicate data = false
    directory_entry_table_starting_block_index: int  # savegames with duplicate data = true
    directory_entry_table_block_count: int  # savegames with duplicate data = true
    maximum_directory_count: int

    file_entry_table_offset: int  # savegames with duplicate data = false
    file_entry_table_starting_block_index: int  # savegames with duplicate data = true
    file_entry_table_block_count: int  # savegames with duplicate data = true
    maximum_file_count: int

    @classmethod
    def from_bytes(cls, data: bytes):
        if len(data) != 0x68:
            raise Exception('fsinfo is not 0x68')

        data_region_offset = readle(data[0x38:0x40])

        special_keys = {}
        if data_region_offset:  # savegames with duplicate data = true
            special_keys['directory_entry_table_starting_block_index'] = readle(data[0x48:0x4C])
            special_keys['directory_entry_table_block_count'] = readle(data[0x4C:0x50])
            special_keys['file_entry_table_starting_block_index'] = readle(data[0x58:0x5C])
            special_keys['file_entry_table_block_count'] = readle(data[0x5C:0x60])

            special_keys['directory_entry_table_offset'] = -1
            special_keys['file_entry_table_offset'] = -1
        else:  # savegames with duplicate_data = false
            special_keys['directory_entry_table_offset'] = readle(data[0x48:0x50])
            special_keys['file_entry_table_offset'] = readle(data[0x58:0x60])

            special_keys['directory_entry_table_starting_block_index'] = -1
            special_keys['directory_entry_table_block_count'] = -1
            special_keys['file_entry_table_starting_block_index'] = -1
            special_keys['file_entry_table_block_count'] = -1

        return cls(data_region_block_size=readle(data[0x4:0x8]),
                   directory_hash_table_offset=readle(data[0x8:0x10]),
                   directory_hash_table_bucket_count=readle(data[0x10:0x14]),
                   file_hash_table_offset=readle(data[0x18:0x20]),
                   file_hash_table_bucket_count=readle(data[0x20:0x24]),
                   file_allocation_table_offset=readle(data[0x28:0x30]),
                   file_allocation_table_entry_count=readle(data[0x30:0x34]),
                   data_region_offset=data_region_offset,
                   data_region_block_count=readle(data[0x40:0x44]),
                   # special keys would normally be next by order of the original structure
                   maximum_directory_count=readle(data[0x50:0x54]),
                   maximum_file_count=readle(data[0x60:0x64]),
                   **special_keys)

    @classmethod
    def load(cls, fp):
        return cls.from_bytes(fp.read(0x68))


DirEntrySAVEVSXEStruct = Struct('<I 16s I I I 4x I')


class DirEntrySAVEVSXE(NamedTuple):
    parent_directory_index: int
    name: str
    next_sibling_directory_index: int
    first_subdirectory_index: int
    first_file_index: int
    next_directory_in_same_hash_table_bucket: int

    @classmethod
    def from_bytes(cls, data: bytes):
        unpacked = DirEntrySAVEVSXEStruct.unpack(data)

        return cls(parent_directory_index=unpacked[0],
                   name=unpacked[1].rstrip(b'\0').decode('ascii'),
                   next_sibling_directory_index=unpacked[2],
                   first_subdirectory_index=unpacked[3],
                   first_file_index=unpacked[4],
                   next_directory_in_same_hash_table_bucket=unpacked[5])

    @classmethod
    def load(cls, fp: 'BinaryIO'):
        return cls.from_bytes(fp.read(DirEntrySAVEVSXEStruct.size))


# only first file index matters here as BDRI only has one root folder
# all the other 4x values are all zero
DirEntryBDRIStruct = Struct('<4x 4x 4x I 12x 4x')


class DirEntryBDRI(NamedTuple):
    first_file_index: int

    @classmethod
    def from_bytes(cls, data: bytes):
        unpacked = DirEntryBDRIStruct.unpack(data)

        return cls(*unpacked)

    @classmethod
    def load(cls, fp: 'BinaryIO'):
        return cls.from_bytes(fp.read(DirEntryBDRIStruct.size))


DirEntryDummySAVEBDRIStruct = Struct('<I I 28x I')


class DirEntryDummy(NamedTuple):
    current_total_entry_count: int
    maximum_entry_count: int
    next_dummy_entry: int

    @classmethod
    def from_bytes(cls, data: bytes):
        return cls(*DirEntryDummySAVEBDRIStruct.unpack(data))

    @classmethod
    def load(cls, fp: 'BinaryIO'):
        return cls.from_bytes(fp.read(DirEntryDummySAVEBDRIStruct.size))


FileEntrySAVEStruct = Struct('<I 16s I 4x I Q 4x I')


class FileEntrySAVE(NamedTuple):
    parent_directory_index: int
    name: str
    next_sibling_file_index: int
    first_block_index: int
    size: int
    next_file_in_same_hash_table_bucket: int

    @classmethod
    def from_bytes(cls, data: bytes):
        unpacked = FileEntrySAVEStruct.unpack(data)

        return cls(parent_directory_index=unpacked[0],
                   name=unpacked[1].rstrip(b'\0').decode('ascii'),
                   next_sibling_file_index=unpacked[2],
                   first_block_index=unpacked[3],
                   size=unpacked[4],
                   next_file_in_same_hash_table_bucket=unpacked[5])

    @classmethod
    def load(cls, fp):
        return cls.from_bytes(fp.read(FileEntrySAVEStruct.size))


FileEntryBDRIStruct = Struct('<I Q I 4x I Q 8x I')


class FileEntryBDRI(NamedTuple):
    parent_directory_index: int
    title_id: int
    next_sibling_file_index: int
    first_block_index: int
    size: int
    next_file_in_same_hash_table_bucket: int

    @classmethod
    def from_bytes(cls, data: bytes):
        unpacked = FileEntryBDRIStruct.unpack(data)

        return cls(parent_directory_index=unpacked[0],
                   title_id=unpacked[1],
                   next_sibling_file_index=unpacked[2],
                   first_block_index=unpacked[3],
                   size=unpacked[4],
                   next_file_in_same_hash_table_bucket=unpacked[5])

    @classmethod
    def load(cls, fp):
        return cls.from_bytes(fp.read(FileEntryBDRIStruct.size))


FATEntryStruct = Struct('<I I')


class FATEntry(NamedTuple):
    index_u: int
    flag_u: bool
    index_v: int
    flag_v: bool

    @classmethod
    def from_bytes(cls, data: bytes):
        u, v = FATEntryStruct.unpack(data)

        return cls(index_u=(u & 0x7FFFFFFF),
                   flag_u=bool(u & 0x80000000),
                   index_v=(v & 0x7FFFFFFF),
                   flag_v=bool(v & 0x80000000))

    @classmethod
    def load(cls, fp):
        return cls.from_bytes(fp.read(8))


def iterate_fat(index: int, fat: 'BinaryIO'):
    data_block_indexes = []
    while True:
        fat.seek(index * 8)
        fentry = FATEntry.load(fat)
        data_block_indexes.append(index - 1)
        if fentry.flag_v:
            fentry_exp_first = FATEntry.load(fat)
            data_block_indexes.extend(range(fentry_exp_first.index_u, fentry_exp_first.index_v))
        index = fentry.index_v
        if not index:
            break

    return data_block_indexes


def get_bucket(name: str, parent_dir_index: int, bucket_count: int) -> int:
    bname = name.encode('ascii').ljust(16, b'\0')
    bhash = parent_dir_index ^ 0x091A2B3C
    for i in range(4):
        bhash = ((bhash >> 1) | (bhash << 31)) & 0xFFFFFFFF
        bhash ^= bname[i * 4]
        bhash ^= bname[i * 4 + 1] << 8
        bhash ^= bname[i * 4 + 2] << 16
        bhash ^= bname[i * 4 + 3] << 24
    return bhash % bucket_count


class InnerFATOpenFile(RawIOBase):
    def __init__(self, reader: 'BinaryIO', data_indexes: 'List[int]', size: int, block_size: int,
                 read_only: bool = True):
        if not read_only:
            raise NotImplementedError('writing is not yet supported')

        self._reader = reader
        self._data_indexes = data_indexes
        self._size = size
        self._block_size = block_size
        self._read_only = read_only

        file_id = id(reader)
        try:
            self._lock = _lock_objects[file_id]
        except KeyError:
            self._lock = Lock()
            _lock_objects[file_id] = self._lock

        self._last_block_size = size % block_size
        if self._last_block_size == 0:
            self._last_block_size = block_size

        # The seek over the current file, returned by tell().
        self._fake_seek = 0
        # Current file index and seek on it.
        self._seek_info = (0, 0)
        # (data offset, logical offset, chunk size)
        self._chunks = []
        curr_offset = 0

        for idx in data_indexes:
            self._chunks.append((idx * block_size, curr_offset, block_size))
            curr_offset += block_size

    def _calc_seek(self, pos: int):
        self._fake_seek = pos
        for idx, info in enumerate(self._chunks):
            if info[1] <= pos < info[1] + info[2]:
                self._seek_info = (idx, pos - info[1])
                break

    def close(self):
        super().close()
        self._chunks = ()

    def __del__(self):
        self.close()

    @_raise_if_file_closed
    def seek(self, pos: int, whence: int = 0):
        if whence == 0:
            if pos < 0:
                raise ValueError('negative seek value')
            self._calc_seek(pos)
        elif whence == 1:
            if self._fake_seek - pos < 0:
                pos = 0
            self._calc_seek(self._fake_seek + pos)
        elif whence == 2:
            if self._size + pos < 0:
                pos = -self._size
            self._calc_seek(self._size + pos)
        else:
            if isinstance(whence, int):
                raise ValueError(f'whence value {whence} unsupported')
            else:
                raise TypeError(f'an integer is required (got type {type(whence).__name__})')
        return self._fake_seek

    @_raise_if_file_closed
    def tell(self) -> int:
        return self._fake_seek

    @_raise_if_file_closed
    def read(self, n: int = -1):
        if n == -1:
            n = max(self._size - self._fake_seek, 0)
        elif self._fake_seek + n > self._size:
            n = max(self._size - self._fake_seek, 0)
        if n == 0:
            return b''

        left = n
        current_index, start_seek = self._seek_info

        full_data = []

        with self._lock:
            while True:
                info = self._chunks[current_index]
                offset = info[0]
                real_seek = offset + start_seek
                to_read = min(info[2] - start_seek, left)

                self._reader.seek(real_seek)
                full_data.append(self._reader.read(to_read))
                self._fake_seek += to_read

                left -= to_read
                if left <= 0:
                    break
                current_index += 1
                start_seek = 0

            self._seek_info = (current_index, self._fake_seek - self._chunks[current_index][1])

        return b''.join(full_data)

    @_raise_if_file_closed
    def write(self, s: bytes) -> int:
        raise NotImplementedError

    @_raise_if_file_closed
    def readable(self) -> bool:
        return True

    @_raise_if_file_closed
    def writable(self) -> bool:
        return not self._read_only

    @_raise_if_file_closed
    def seekable(self) -> bool:
        return True
