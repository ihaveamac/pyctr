# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from typing import TYPE_CHECKING, NamedTuple

from ...common import PyCTRError

if TYPE_CHECKING:
    from typing import BinaryIO, Dict
    from ...common import FilePath


CONFIG_SAVE_SIZE = 0x8000
BLOCK_ENTRY_SIZE = 0xC
ALLOWED_FLAGS = frozenset({0x8, 0xC, 0xA, 0xE})


class ConfigSaveError(PyCTRError):
    """Generic error for Config Save operations."""


class InvalidConfigSaveError(ConfigSaveError):
    """Config Save is corrupted."""


class OutOfSpaceConfigSaveError(ConfigSaveError):
    """Config Save generation ran out of space for data."""


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

    __slots__ = ('blocks',)

    def __init__(self):
        self.blocks: Dict[int, BlockInfo] = {}

    def __bytes__(self):
        return self.to_bytes()

    def to_bytes(self):
        """
        Converts the object to a raw config save file.

        CFG adds new block from end to start of file for any block > 4 bytes.
        Any block <= 4 bytes only get a block entry.

        :return: Raw config save data.
        """
        raw_entries = []
        raw_block_datas = []

        # offset starts at the end of the file
        # this decrements per each data block that is bigger than 4 bytes
        current_offset = CONFIG_SAVE_SIZE

        # header + block entries
        data_offset_limit = 4 + len(self.blocks) * BLOCK_ENTRY_SIZE

        for block_id, block_entry in self.blocks.items():
            data_size = len(block_entry.data)
            raw_entry_list = [
                block_id.to_bytes(4, 'little'),
                None,
                data_size.to_bytes(2, 'little'),
                block_entry.flags.to_bytes(2, 'little')
            ]

            if data_size > 4:
                current_offset -= data_size
                if current_offset < data_offset_limit:
                    raise OutOfSpaceConfigSaveError("Too much block data for this save!")

                raw_entry_list[1] = current_offset.to_bytes(4, 'little')
                raw_block_datas.insert(0, block_entry.data)
            else:
                raw_entry_list[1] = block_entry.data.ljust(4, b'\0')

            raw_entries.append(b''.join(raw_entry_list))

        hdr_and_entries = b''.join((
            len(self.blocks).to_bytes(2, 'little'),
            current_offset.to_bytes(2, 'little'),
            *raw_entries
        ))
        blks_data = b''.join(raw_block_datas)

        if len(hdr_and_entries) != data_offset_limit:
            raise ConfigSaveError("Something failed while making bytes, unexpected length of header and entries. Likely coding bug.")

        if current_offset != CONFIG_SAVE_SIZE - len(blks_data):
            raise ConfigSaveError("Something failed while making bytes, invalid data offset. Likely coding bug.")

        config = b''.join((
            hdr_and_entries,
            bytes(CONFIG_SAVE_SIZE - len(blks_data) - len(hdr_and_entries)),
            blks_data
        ))

        if len(config) != CONFIG_SAVE_SIZE:
            raise ConfigSaveError("Something failed while making bytes, invalid bytes len. Likely coding bug.")

        return config

    def save(self, fn: 'FilePath'):
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

        if flags is None:
            if block_id in self.blocks:
                flags = self.blocks[block_id].flags
            else:
                flags = 0xE

        if flags not in ALLOWED_FLAGS:
            raise BlockFlagsNotAllowed(flags)

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

        block_entries_roof = 4 + BLOCK_ENTRY_SIZE * entry_count
        if block_entries_roof > data_offset:
            raise InvalidConfigSaveError(f'Data offset overlapped with entry headers')

        block_entries = raw_save[4:block_entries_roof]

        last_offset = CONFIG_SAVE_SIZE

        def load_raw_block_entry(b: bytes):
            block_id = int.from_bytes(b[0:4], 'little')
            block_size = int.from_bytes(b[0x8:0xA], 'little')
            block_flags = int.from_bytes(b[0xA:0xC], 'little')

            if block_size > 4:
                block_data_offset = int.from_bytes(b[4:8], 'little')
                block_data = raw_save[block_data_offset:block_data_offset + block_size]
            else:
                block_data_offset = -1
                block_data = b[4:4 + block_size]

            return {
                'id': block_id,
                'flags': block_flags,
                'data': block_data,
                'offset': block_data_offset,
                'size': block_size
            }

        def sanity_check_blk(last_off: int, block: dict) -> int:
            if block['size'] <= 4:
                return last_off
            last_off -= block['size']
            if last_off != block['offset'] or last_off < data_offset:
                raise InvalidConfigSaveError(f'Save not sane! May be corrupted.')
            return last_off

        cfg_save = cls()
        for x in range(entry_count):
            entry = block_entries[x * BLOCK_ENTRY_SIZE:(x + 1) * BLOCK_ENTRY_SIZE]
            block = load_raw_block_entry(entry)
            last_offset = sanity_check_blk(last_offset, block)
            cfg_save.set_block(block['id'], block['data'], block['flags'])

        return cfg_save

    @classmethod
    def from_file(cls, fn: 'FilePath'):
        with open(fn, 'rb') as f:
            return cls.load(f)
