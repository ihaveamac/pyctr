# This file is a part of pyctr.
#
# Copyright (c) 2017-2020 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from hashlib import sha256
from io import RawIOBase
from threading import Lock, RLock
from typing import TYPE_CHECKING, NamedTuple

from ....fileio import SubsectionIO
from ....util import readle, roundup
from .common import (InvalidHeaderError, InvalidHeaderLengthError, PartitionDescriptorError, LevelData,
                     _raise_if_level_closed, get_block_range)

if TYPE_CHECKING:
    from typing import BinaryIO, Callable, List, Optional, Tuple

    # trick type checkers
    RawIOBase = BinaryIO

EMPTY_HASH = b'\0' * 0x20


class IVFCReadOnlyError(PartitionDescriptorError):
    """The DPFS level is read-only."""


class IVFC(NamedTuple):
    master_hash_size: int

    lv1: 'LevelData'
    lv2: 'LevelData'
    lv3: 'LevelData'
    lv4: 'LevelData'

    descriptor_size: int  # usually 0x78

    @classmethod
    def from_bytes(cls, data: bytes):
        magic = data[0:8]
        if magic != b'IVFC\0\0\2\0':
            raise InvalidHeaderError(f'IVFC expected, got {data!r}')

        if len(data) != 0x78:
            raise InvalidHeaderLengthError(f'IVFC expected length 0x78, got {hex(len(data))}')

        levels = {}
        for lvl in range(1, 5):
            offs = 0x10 + ((lvl - 1) * 0x18)
            block_size_log2 = readle(data[offs+0x10:offs+0x14])
            level_data = LevelData(offset=readle(data[offs:offs+0x8]),
                                   size=readle(data[offs+0x8:offs+0x10]),
                                   block_size_log2=block_size_log2,
                                   block_size=1 << block_size_log2)

            levels[f'lv{lvl}'] = level_data

        # noinspection PyArgumentList
        return cls(master_hash_size=readle(data[0x8:0x10]),
                   descriptor_size=readle(data[0x70:0x78]),
                   **levels)

    def to_bytes(self):
        parts = [b'IVFC\0\0\2\0', self.master_hash_size.to_bytes(8, 'little')]
        for lvl in range(1, 5):
            level_data = getattr(self, f'lv{lvl}')
            parts.append(level_data.offset.to_bytes(8, 'little'))
            parts.append(level_data.size.to_bytes(8, 'little'))
            parts.append(level_data.block_size_log2.to_bytes(4, 'little'))
            parts.append(b'\0\0\0\0')  # padding
        parts.append(self.descriptor_size.to_bytes(8, 'little'))

        return b''.join(parts)


class IVFCLevel4Reader(RawIOBase):
    def __init__(self, tree: 'IVFCHashTree', verify: bool = True, deep_verify: bool = True):
        self._tree = tree
        self._verify = verify
        self._deep_verify = deep_verify

        # noinspection PyProtectedMember
        self._lv4 = self._tree._ivfc.lv4

        self._seek = 0
        self._lock = Lock()

    @_raise_if_level_closed
    def read(self, size: int = -1) -> bytes:
        if size == -1:
            size = self._lv4.size

        if self._seek >= self._lv4.size:
            # avoid sending useless requests past the file
            return b''

        with self._lock:
            starting_block, ending_block = get_block_range(self._seek, size, self._lv4.block_size)

            blocks = []

            for block in range(starting_block, ending_block + 1):
                data, valid = self._tree.get_block(4, block, verify=self._verify, deep_verify=self._deep_verify)
                if self._verify and not valid:
                    # data isn't always block-aligned
                    blocks.append(b'\xDD' * len(data))
                else:
                    blocks.append(data)

            first_block_offset = self._seek % self._lv4.block_size
            if starting_block == ending_block:
                last_block_size = size % self._lv4.block_size
            else:
                last_block_size = (first_block_offset + size) % self._lv4.block_size

            if not last_block_size:
                last_block_size = self._lv4.block_size

            blocks[0] = blocks[0][first_block_offset:]
            blocks[-1] = blocks[-1][:last_block_size]

            final_data = b''.join(blocks)
            self._seek += len(final_data)
            return final_data

    @_raise_if_level_closed
    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            if offset < 0:
                raise ValueError(f'negative seek value {offset}')
            self._seek = min(offset, self._lv4.size)
        elif whence == 1:
            self._seek = max(self._seek + offset, 0)
        elif whence == 2:
            self._seek = max(self._lv4.size + offset, 0)
        return self._seek

    @_raise_if_level_closed
    def write(self, data: bytes) -> int:
        if self._seek + len(data) > self._lv4.size:
            data = data[:self._lv4.size - self._seek]

        with self._lock:
            self._tree.write_data(4, self._seek, data)

            return len(data)


class IVFCHashTree:
    """
    Implements an IVFC hash tree. This covers levels 1, 2, and 3. IVFC Level 4 contains the actual data.

    :param fp: A file-like object with levels 1, 2, and 3. If `lv4_fp` is not specified, this must also contain level 4.
    :param master_hashes: Master hashes from the partition descriptor, which verify IVFC Level 1.
    :param lv4_fp: A file-like object with level 4. Only used if the DIFI header has enabled external IVFC Level 4.
    :param update_master_hashes_callback: Function to be called when master hashes are updated. This is used by DISA and
        DIFF to write the master hashes to the partition descriptor.
    """

    def __init__(self, fp: 'BinaryIO', ivfc: 'IVFC', master_hashes: 'List[bytes]', *, lv4_fp: 'BinaryIO' = None,
                 update_master_hashes_callback: 'Callable[[List[bytes]], None]' = None):
        self._fp = fp
        self._ivfc = ivfc
        self._lv4_fp = lv4_fp
        self._master_hashes = master_hashes

        if update_master_hashes_callback:
            self._update_master_hashes_callback = update_master_hashes_callback
        else:
            # dummy function in case this class is not being run from a DISA/DIFF archive
            self._update_master_hashes_callback = lambda x: len(x)

        # lv1 cache should be the same for both normal and deep verify
        lv1_cache = {}

        # Store the results of the validity of blocks, to avoid unnecessary re-calculation.
        self._valid_results_cache = [lv1_cache, {}, {}, {}]
        # Store the results of the deep validity of blocks, to avoid even more unnecessary re-calculation.
        self._deep_valid_results_cache = [lv1_cache, {}, {}, {}]

        # RLock is used because get_block calls itself for deep verification, and write_block calls itself to update
        #   hashes in upper levels.
        self._rlock = RLock()

        real_lv4_fp = lv4_fp if lv4_fp else SubsectionIO(self._fp, ivfc.lv4.offset, ivfc.lv4.size)

        # This isn't very good honestly... I think I'll rewrite this at some point.
        self.levels: List[Tuple[LevelData, BinaryIO]] = [
            (ivfc.lv1, SubsectionIO(self._fp, ivfc.lv1.offset, ivfc.lv1.size)),
            (ivfc.lv2, SubsectionIO(self._fp, ivfc.lv2.offset, ivfc.lv2.size)),
            (ivfc.lv3, SubsectionIO(self._fp, ivfc.lv3.offset, ivfc.lv3.size)),
            (ivfc.lv4, real_lv4_fp),
        ]

    def get_block(self, level: int, block: int, *, verify: bool = True,
                  deep_verify: bool = True) -> 'Tuple[bytes, Optional[bool]]':
        """
        Get the data from a block. The data is validated using the IVFC levels above the requested one.

        :param level: Level containing the data.
        :param block: The block to read.
        :param verify: Verify the block's hash using the level above.
        :param deep_verify: Verify the hashes in all above levels, not just the upper.
        :return: The data, and if the hash of it was valid. `True` if valid, `False` if invalid, `None` if uninitialized
            (expected hash is all zeros) or `verify` was false.
        """

        level_index = level - 1

        if verify:
            # determine which cache to use depending on if the data is being deep verified
            cache = (self._deep_valid_results_cache if deep_verify else self._valid_results_cache)[0]

            with self._rlock:
                if block in cache:
                    block_data, _ = self._get_block_internal(level_index, block, verify=False)
                    return block_data, cache[block]
                else:
                    block_data, valid = self._get_block_internal(level_index, block, verify=True,
                                                                 deep_verify=deep_verify)
                    cache[block] = valid
                    return block_data, valid
        else:
            return self._get_block_internal(level_index, block, verify=verify, deep_verify=deep_verify)

    def _get_block_internal(self, level_index: int, block: int, *, verify: bool = True,
                            deep_verify: bool = True) -> 'Tuple[bytes, Optional[bool]]':
        """The actual method that gets the block data and validates it. Cache is handled by :meth:`get_block`."""

        with self._rlock:
            level_data, level_fp = self.levels[level_index]
            block_offset = block * level_data.block_size
            level_fp.seek(block_offset)
            block_data = level_fp.read(level_data.block_size)

            if verify:
                block_data_padded = block_data.ljust(level_data.block_size, b'\0')

                if level_index == 0:
                    master_hash = self._master_hashes[block]
                    return block_data, master_hash == sha256(block_data_padded).digest()
                else:
                    # cheap way of getting the upper level
                    upper_level = level_index
                    upper_level_index = upper_level - 1
                    upper_level_data, upper_level_fp = self.levels[upper_level_index]
                    hash_position = block * 0x20

                    if deep_verify:
                        block_with_hash = hash_position // upper_level_data.block_size
                        block_with_hash_is_valid = self.get_block(upper_level, block_with_hash, verify=True,
                                                                  deep_verify=True)
                        if not block_with_hash_is_valid[1]:
                            # if the upper level determined the block with this hash is invalid, assume the data is
                            #   invalid too without checking it
                            return block_data, block_with_hash_is_valid[1]

                    upper_level_fp.seek(hash_position)
                    expected_hash = upper_level_fp.read(0x20)
                    if expected_hash == EMPTY_HASH:
                        # uninitialized region
                        return block_data, None
                    return block_data, expected_hash == sha256(block_data_padded).digest()

            else:
                return block_data, None

    def write_data(self, level: int, offset: int, data: bytes):
        """
        Write the data to a level. This will update hashes in the above levels.

        :param level: Level to write the data to.
        :param offset: The offset to write the data to.
        :param data: Data to write.
        :return:
        """

        if self._fp.writable():
            level_index = level - 1

            # for updating hashes in above levels
            hashes = []

            with self._rlock:
                level_data, level_fp = self.levels[level_index]

                starting_block = (roundup(offset - level_data.block_size + 1,
                                          level_data.block_size)) // level_data.block_size

                ending_block = max(((roundup(offset + len(data), level_data.block_size)) // level_data.block_size) - 1,
                                   starting_block)

                level_fp.seek(offset)
                level_fp.write(data)

                level_fp.seek(starting_block)

                for x in range(starting_block, ending_block + 1):
                    block_data = level_fp.read(level_data.block_size)
                    block_data_padded = block_data.ljust(level_data.block_size, b'\0')
                    hashes.append(sha256(block_data_padded).digest())

                if level == 1:
                    for idx, h in enumerate(hashes, starting_block):
                        self._master_hashes[idx] = h
                    self._update_master_hashes_callback(self._master_hashes)
                else:
                    # cheap way of getting the upper level
                    upper_level = level_index
                    hash_position = starting_block * 0x20
                    self.write_data(upper_level, hash_position, b''.join(hashes))

        else:
            raise IVFCReadOnlyError('IVFC was opened on a read-only file')
