# This file is a part of pyctr.
#
# Copyright (c) 2017-2021 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from typing import NamedTuple

from ....util import readle
from .common import InvalidHeaderError, InvalidHeaderLengthError


class DIFI(NamedTuple):
    ivfc_offset: int
    ivfc_size: int

    dpfs_offset: int
    dpfs_size: int

    part_hash_offset: int
    part_hash_size: int

    enable_external_ivfc_lv4: bool

    dpfs_tree_lv1_selector: int

    external_ivfc_lv4_offset: int

    @classmethod
    def from_bytes(cls, data: bytes):
        magic = data[0:8]
        if magic != b'DIFI\0\0\1\0':
            raise InvalidHeaderError(f'DIFI expected, got {data!r}')

        if len(data) != 0x44:
            raise InvalidHeaderLengthError(f'DIFI expected length 0x44, got {len(data):#x}')

        # noinspection PyArgumentList
        return cls(ivfc_offset=readle(data[0x8:0x10]),
                   ivfc_size=readle(data[0x10:0x18]),
                   dpfs_offset=readle(data[0x18:0x20]),
                   dpfs_size=readle(data[0x20:0x28]),
                   part_hash_offset=readle(data[0x28:0x30]),
                   part_hash_size=readle(data[0x30:0x38]),
                   enable_external_ivfc_lv4=bool(data[0x38]),
                   dpfs_tree_lv1_selector=data[0x39],
                   external_ivfc_lv4_offset=readle(data[0x3C:0x44]))

    def to_bytes(self):
        parts = [b'DIFI\0\0\1\0',
                 self.ivfc_offset.to_bytes(8, 'little'), self.ivfc_size.to_bytes(8, 'little'),
                 self.dpfs_offset.to_bytes(8, 'little'), self.dpfs_size.to_bytes(8, 'little'),
                 self.part_hash_offset.to_bytes(8, 'little'), self.part_hash_size.to_bytes(8, 'little'),
                 self.enable_external_ivfc_lv4.to_bytes(1, 'little'), self.dpfs_tree_lv1_selector.to_bytes(1, 'little'),
                 b'\0\0', self.external_ivfc_lv4_offset.to_bytes(8, 'little')]

        return b''.join(parts)
