# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from enum import IntEnum
from typing import TYPE_CHECKING

from .save import BlockIDNotFoundError, ConfigSaveReader, KNOWN_BLOCKS

if TYPE_CHECKING:
    from typing import BinaryIO, Union
    from ...common import FilePath


class SystemModel(IntEnum):
    Old3DS = 0
    Old3DSXL = 1
    New3DS = 2
    Old2DS = 3
    New3DSXL = 4
    New2DSXL = 5


class ConfigSaveBlockParser:
    """
    Parses config blocks to provide easy access to information in the config save.

    https://www.3dbrew.org/wiki/Config_Savegame
    """

    def __init__(self, save: 'ConfigSaveReader'):
        self.save = save

    @property
    def username(self) -> str:
        """
        Profile username. Can be up to 10 characters long.

        Block ID: 0x000A0000
        """

        username_raw = self.save.get_block(0x000A0000)
        username = username_raw.data.decode('utf-16le')
        # sometimes there seems to be garbage after the null terminator
        # so we can't just do a trim
        null_term_pos = username.find('\0')
        if null_term_pos >= 0:
            username = username[:null_term_pos]

        return username

    @username.setter
    def username(self, value: str):
        username_raw = value.encode('utf-16le').ljust(KNOWN_BLOCKS[0x000A0000]["size"], b'\0')
        self.save.set_block(0x000A0000, username_raw)

    @property
    def user_time_offset(self) -> int:
        """
        The offset to the Raw RTC in milliseconds.

        Block ID: 0x00030001
        """
        time_offset_raw = self.save.get_block(0x00030001)
        return int.from_bytes(time_offset_raw.data, 'little')

    @user_time_offset.setter
    def user_time_offset(self, value: int):
        time_offset_raw = value.to_bytes(KNOWN_BLOCKS[0x00030001]["size"], "little")
        self.save.set_block(0x00030001, time_offset_raw)

    @property
    def system_model(self) -> SystemModel:
        """
        System model.

        Block ID: 0x000F0004
        """

        system_model_raw = self.save.get_block(0x000F0004)
        return SystemModel(system_model_raw.data[0])

    @system_model.setter
    def system_model(self, value: 'Union[int, SystemModel]'):
        # this field is actually 4 bytes
        # just in case, we'll preserve the next 3 bytes (their use is unknown)
        try:
            system_model_raw = bytearray(self.save.get_block(0x000F0004).data)
        except BlockIDNotFoundError:
            system_model_raw = bytearray(4)
        system_model_raw[0] = value
        self.save.set_block(0x000F0004, system_model_raw)

    @classmethod
    def load(cls, fp: 'BinaryIO'):
        return cls(ConfigSaveReader.load(fp))

    @classmethod
    def from_file(cls, fn: 'FilePath'):
        return cls(ConfigSaveReader.from_file(fn))
