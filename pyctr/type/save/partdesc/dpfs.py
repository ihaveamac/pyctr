# This file is a part of pyctr.
#
# Copyright (c) 2017-2020 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from io import RawIOBase
from threading import Lock
from typing import TYPE_CHECKING, NamedTuple

from ....util import readle
from .common import (PartitionDescriptorError, InvalidHeaderError, InvalidHeaderLengthError, LevelData,
                     get_block_range, read_le_u32_array, _raise_if_level_closed)

if TYPE_CHECKING:
    from typing import BinaryIO, List

    # trick type checkers
    RawIOBase = BinaryIO


class DPFSReadOnlyError(PartitionDescriptorError):
    """The DPFS level is read-only."""


class DPFS(NamedTuple):
    lv1: 'LevelData'
    lv2: 'LevelData'
    lv3: 'LevelData'

    @classmethod
    def from_bytes(cls, data: bytes):
        magic = data[0:8]
        if magic != b'DPFS\0\0\1\0':
            raise InvalidHeaderError(f'DPFS expected, got {data!r}')

        if len(data) != 0x50:
            raise InvalidHeaderLengthError(f'DPFS expected length 0x50, got {hex(len(data))}')

        levels = {}
        for lvl in range(1, 4):
            offs = 0x8 + ((lvl - 1) * 0x18)
            block_size_log2 = readle(data[offs+0x10:offs+0x14])
            level_data = LevelData(offset=readle(data[offs:offs+0x8]),
                                   size=readle(data[offs+0x8:offs+0x10]),
                                   block_size_log2=block_size_log2,
                                   block_size=1 << block_size_log2)

            levels[f'lv{lvl}'] = level_data

        # noinspection PyArgumentList
        return cls(**levels)

    def to_bytes(self):
        parts = [b'DPFS\0\0\1\0']

        for lvl in range(1, 4):
            level_data = getattr(self, f'lv{lvl}')
            parts.append(level_data.offset.to_bytes(8, 'little'))
            parts.append(level_data.size.to_bytes(8, 'little'))
            parts.append(level_data.block_size_log2.to_bytes(4, 'little'))
            parts.append(b'\0\0\0\0')  # padding

        return b''.join(parts)


class DPFSLevelChunkBase:
    u32_list: 'List[int]'

    def get_active_bit(self, bit: int):
        # get the index of the list to read, then get the appropriate u32
        current_u32 = self.u32_list[bit >> 5]

        bit_offset = (31 - (bit % 32))

        return bool((current_u32 >> bit_offset) & 1)

    def get_all_active_bits(self):
        for u32 in self.u32_list:
            for curr in range(31, -1, -1):
                yield u32 >> curr & 1


class DPFSLevel1(DPFSLevelChunkBase):
    """
    Reads the contents of DPFS Level 1. In the DPFS tree, this contains bits that determine which blocks are active in
    DPFS Level 2.

    :param data:
    :param tree_selector:
    """

    def __init__(self, data: bytes, tree_selector: int):
        orig_data_len = len(data)
        self.tree_selector = tree_selector

        if self.tree_selector:
            active_data = data[orig_data_len // 2:]
        else:
            active_data = data[:orig_data_len // 2]

        self.u32_list = list(read_le_u32_array(active_data))


class DPFSLevel2(DPFSLevelChunkBase):
    """
    Reads the contents of DPFS Level 2. In the DPFS tree, this contains bits that determine which blocks are active in
    DPFS Level 3.

    :param data: The DPFS Level 2 data.
    :param block_size_log2: Block size in log2.
    :param lv1: Level 1 to read active bits from.
    """

    def __init__(self, data: bytes, block_size: int, lv1: 'DPFSLevel1'):
        self.lv1 = lv1
        orig_data_len = len(data)
        data_len_half = orig_data_len // 2

        self.u32_list = []

        for active_chunk, offs in zip(lv1.get_all_active_bits(), range(0, data_len_half, block_size)):
            chunk_offset = data_len_half if active_chunk else 0

            block_data = data[offs + chunk_offset:offs + chunk_offset + block_size]

            for u32 in read_le_u32_array(block_data):
                self.u32_list.append(u32)


class DPFSLevel3FileIO(RawIOBase):
    def __init__(self, lv3: 'DPFSLevel3'):
        self._lv3 = lv3
        self._seek = 0
        self._lock = Lock()

    @_raise_if_level_closed
    def read(self, size: int = -1) -> bytes:
        if size == -1:
            size = self._lv3.size - self._seek

        with self._lock:
            data = b''.join(self._lv3.get_data(self._seek, size))
            self._seek += len(data)
            return data

    @_raise_if_level_closed
    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            if offset < 0:
                raise ValueError(f'negative seek value {offset}')
            self._seek = min(offset, self._lv3.size)
        elif whence == 1:
            self._seek = max(self._seek + offset, 0)
        elif whence == 2:
            self._seek = max(self._lv3.size + offset, 0)
        return self._seek

    @_raise_if_level_closed
    def write(self, data: bytes) -> int:
        with self._lock:
            written = self._lv3.write_data(self._seek, data)
            self._seek += written
            return written

    @_raise_if_level_closed
    def tell(self) -> int:
        return self._seek

    @_raise_if_level_closed
    def readable(self) -> bool:
        return True

    @_raise_if_level_closed
    def writable(self) -> bool:
        # noinspection PyProtectedMember
        return self._lv3._fp.writable()

    @_raise_if_level_closed
    def seekable(self) -> bool:
        return True


class DPFSLevel3:
    """
    Reads the contents of DPFS Level 3. In the DPFS tree, this contains the actual data.

    :param fp: A file-like object with the DPFS Level 3 data.
    :param size: Size of the level. This should be the size of the final data, meaning the actual data read would be
        twice this size to account for the two chunks.
    :param block_size: Block size.
    :param lv2: Level 2 to read active bits from.
    """

    def __init__(self, fp: 'BinaryIO', size: int, block_size: int, lv2: 'DPFSLevel2'):
        self._fp = fp
        self._start = self._fp.tell()
        self._block_size = block_size
        self.lv2 = lv2

        self._lock = Lock()

        self.size = size

    def get_data(self, offset: int, size: int):
        if offset + size > self.size:
            size = self.size - offset
        starting_block, ending_block = get_block_range(offset, size, self._block_size)

        blocks = []

        with self._lock:
            for block in range(starting_block, ending_block + 1):
                if self.lv2.get_active_bit(block):
                    chunk_offset = self.size
                else:
                    chunk_offset = 0

                self._fp.seek(chunk_offset + (block * self._block_size))
                data = self._fp.read(self._block_size)
                blocks.append(data)

            first_block_offset = offset % self._block_size
            if starting_block == ending_block:
                last_block_size = size % self._block_size
            else:
                last_block_size = (first_block_offset + size) % self._block_size

            if not last_block_size:
                last_block_size = self._block_size

            blocks[0] = blocks[0][first_block_offset:]
            blocks[-1] = blocks[-1][:last_block_size]

        yield from blocks

    def write_data(self, offset: int, data: bytes):
        bs = self._block_size
        if self._fp.writable():
            if offset + len(data) > self.size:
                data = data[:self.size - offset]
            orig_data_len = len(data)
            starting_block, ending_block = get_block_range(offset, orig_data_len, bs)
            first_block_offset = offset % bs

            data = (b'\0' * first_block_offset) + data

            data_blocks = []
            for x in range(0, len(data), bs):
                data_blocks.append(data[x:x + bs])

            data_blocks[0] = data_blocks[0][first_block_offset:]

            total_written = 0
            with self._lock:
                for block, data_block in enumerate(data_blocks, starting_block):
                    if self.lv2.get_active_bit(block):
                        chunk_offset = self.size
                    else:
                        chunk_offset = 0

                    self._fp.seek(chunk_offset + (block * bs) + first_block_offset)
                    total_written += self._fp.write(data_block)

                    # for laziness
                    first_block_offset = 0

            return total_written

        else:
            raise DPFSReadOnlyError('DPFS level 3 was opened on a read-only file')
