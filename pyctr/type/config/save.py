# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from typing import TYPE_CHECKING, NamedTuple

from ...common import PyCTRError

if TYPE_CHECKING:
    from os import PathLike
    from typing import BinaryIO, Dict, Union


CONFIG_SAVE_SIZE = 0x8000
BLOCK_ENTRY_SIZE = 0xC
ALLOWED_FLAGS = frozenset({0x8, 0xC, 0xA, 0xE})


class ConfigSaveError(PyCTRError):
    """Generic error for Config Save operations."""


class InvalidConfigSaveError(ConfigSaveError):
    """Config Save is corrupted."""


class BlockFlagsNotAllowed(ConfigSaveError):
    """Flags not allowed. Must be 8, 12, 10, or 14 (0x8, 0xC, 0xA, or 0xE)."""

    def __init__(self, flags: int):
        self.flags = flags
        super().__init__(self.flags)

    def __str__(self):
        return f'flags {self.flags} (0x{self.flags:x}) is not allowed, must be 8, 12, 10, or 14 (0x8, 0xC, 0xA, or 0xE).'


class BlockIDNotFoundError(ConfigSaveError):
    """Block ID not found."""

    def __init__(self, block_id: int):
        self.block_id = block_id

    def __str__(self):
        return f'0x{self.block_id:08X}'


class BlockInfo(NamedTuple):
    flags: int
    data: bytes


class ConfigSaveReader:
    """
    Class for 3DS Config Save.

    https://www.3dbrew.org/wiki/Config_Savegame
    """

    __slots__ = ('blocks', 'data_offset')

    data_offset: int
    """
    Offset of the block data region. This is only used when rebuilding the raw save.
    If a config save is loaded, this is overwritten with the offset from that file.
    """

    def __init__(self):
        self.data_offset = 0x41E4
        self.blocks: Dict[int, BlockInfo] = {}

    def __bytes__(self):
        return self.to_bytes()

    def to_bytes(self):
        """
        Converts the object to a raw config save file.

        The result may not be 1:1 identical to the original config file due to garbage data in unused parts, as well as
        offsets shifting around due to Python not always preserving order. This shouldn't matter in practice though.

        :return: Raw config save data.
        """
        raw_entries = []
        raw_block_datas = []

        # offset in the block entry is from the start of the file,
        # so the first one has the offset equal the data region offset
        current_offset = self.data_offset

        for block_id, block_entry in self.blocks.items():
            data_size = len(block_entry.data)
            raw_entry_list = [
                block_id.to_bytes(4, 'little'),
                None,
                data_size.to_bytes(2, 'little'),
                block_entry.flags.to_bytes(2, 'little')
            ]
            if data_size > 4:
                raw_entry_list[1] = current_offset.to_bytes(4, 'little')
                current_offset += data_size
                raw_block_datas.append(block_entry.data)
            else:
                raw_entry_list[1] = block_entry.data.ljust(4, b'\0')
                print(raw_entry_list[1].hex(), data_size)
            raw_entries.append(b''.join(raw_entry_list))

        return b''.join((
            len(self.blocks).to_bytes(2, 'little'),
            self.data_offset.to_bytes(2, 'little'),
            b''.join(raw_entries).ljust(self.data_offset - 4, b'\0'),
            *raw_block_datas
        )).ljust(CONFIG_SAVE_SIZE, b'\0')

    def save(self, fn: 'Union[PathLike, str, bytes]'):
        """
        Save the config save to a file.

        :param fn: File path to write to.
        """
        with open(fn, 'wb') as o:
            o.write(self.to_bytes())

    def set_block(self, block_id: int, data: bytes, flags: int = None):
        """
        Sets or adds a config block.

        :param block_id: Block ID.
        :param flags: Block flags. The purpose is unknown but it's likely access permissions.
            Must be 8, 12, 10, or 14 (0x8, 0xC, 0xA, or 0xE). Defaults to 0xE if block doesn't already exist.
        :param data: Block data.
        """

        if flags not in ALLOWED_FLAGS:
            raise BlockFlagsNotAllowed(flags)

        if not flags:
            if block_id in self.blocks:
                flags = self.blocks[block_id].flags
            else:
                flags = 0xE

        self.blocks[block_id] = BlockInfo(flags=flags, data=data)

    def get_block(self, block_id: int) -> BlockInfo:
        """
        Gets a config block.

        :param block_id: Block ID.
        :return: Block info.
        :rtype: BlockInfo
        """

        try:
            return self.blocks[block_id]
        except KeyError:
            raise BlockIDNotFoundError(block_id)

    def remove_block(self, block_id: int):
        """
        Removes a config block.

        :param block_id: Block ID.
        """

        try:
            del self.blocks[block_id]
        except KeyError:
            raise BlockIDNotFoundError(block_id)

    @classmethod
    def load(cls, fp: 'BinaryIO'):
        raw_save = fp.read(0x8000)

        if len(raw_save) != CONFIG_SAVE_SIZE:
            raise InvalidConfigSaveError(f'Size is not 0x{CONFIG_SAVE_SIZE:08X}')

        header_raw = raw_save[0:4]
        entry_count = int.from_bytes(header_raw[0:2], 'little')
        data_offset = int.from_bytes(header_raw[2:4], 'little')

        block_entries = raw_save[4:data_offset]

        def load_raw_block_entry(b: bytes):
            block_id = int.from_bytes(b[0:4], 'little')
            block_size = int.from_bytes(b[0x8:0xA], 'little')
            block_flags = int.from_bytes(b[0xA:0xC], 'little')

            if block_size > 4:
                block_data_offset = int.from_bytes(b[4:8], 'little')
                block_data = raw_save[block_data_offset:block_data_offset + block_size]
            else:
                block_data = b[4:4 + block_size]

            return {'id': block_id, 'flags': block_flags, 'data': block_data}

        cfg_save = cls()
        cfg_save.data_offset = data_offset
        for x in range(entry_count):
            entry = block_entries[x * BLOCK_ENTRY_SIZE:(x + 1) * BLOCK_ENTRY_SIZE]
            block = load_raw_block_entry(entry)
            cfg_save.set_block(block['id'], block['data'], block['flags'])

        return cfg_save

    @classmethod
    def from_file(cls, fn: 'Union[PathLike, str, bytes]'):
        with open(fn, 'rb') as f:
            return cls.load(f)
