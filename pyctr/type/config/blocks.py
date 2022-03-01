# This file is a part of pyctr.
#
# Copyright (c) 2017-2022 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from enum import IntEnum
from typing import TYPE_CHECKING

from .save import ConfigSaveReader

if TYPE_CHECKING:
    from os import PathLike
    from typing import BinaryIO, Union


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

    def get_username(self) -> str:
        """
        Gets the username.

        Block ID: 0x000A0000

        :return: Username.
        :rtype: str
        """

        username_raw = self.save.get_block(0x000A0000)
        username = username_raw.data.decode('utf-16le')
        # sometimes there seems to be garbage after the null terminator
        # so we can't just do a trim
        null_term_pos = username.find('\0')
        if null_term_pos >= 0:
            username = username[:null_term_pos]

        return username

    def get_user_time_offset(self) -> int:
        """
        Gets the offset to the Raw RTC.

        Block ID: 0x00030001

        :return: Time offset in milliseconds.
        :rtype: int
        """
        time_offset_raw = self.save.get_block(0x00030001)
        return int.from_bytes(time_offset_raw.data, 'little')

    def get_system_model(self) -> SystemModel:
        """
        Gets the system model.

        Block ID: 0x000F0004

        :return: System model.
        :rtype: SystemModel
        """

        system_model_raw = self.save.get_block(0x000F0004)
        return SystemModel(system_model_raw.data[0])

    @classmethod
    def load(cls, fp: 'BinaryIO'):
        return cls(ConfigSaveReader.load(fp))

    @classmethod
    def from_file(cls, fn: 'Union[PathLike, str, bytes]'):
        return cls(ConfigSaveReader.from_file(fn))
