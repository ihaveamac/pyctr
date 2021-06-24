# This file is a part of pyctr.
#
# Copyright (c) 2017-2021 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from struct import pack
from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple

from PIL import Image

from ..common import PyCTRError

if TYPE_CHECKING:
    from os import PathLike
    from typing import BinaryIO, Dict, Mapping, Optional, Tuple, Union

SMDH_SIZE = 0x36C0

region_names = (
    'Japanese',
    'English',
    'French',
    'German',
    'Italian',
    'Spanish',
    'Simplified Chinese',
    'Korean',
    'Dutch',
    'Portuguese',
    'Russian',
    'Traditional Chinese',
)

# the order of the SMDH names to check. the difference here is that English is put before Japanese.
_region_order_check = (
    'English',
    'Japanese',
    'French',
    'German',
    'Italian',
    'Spanish',
    'Simplified Chinese',
    'Korean',
    'Dutch',
    'Portuguese',
    'Russian',
    'Traditional Chinese',
)


class SMDHError(PyCTRError):
    """Generic exception for SMDH operations."""


class InvalidSMDHError(SMDHError):
    """Invalid SMDH contents."""


class AppTitle(NamedTuple):
    short_desc: str
    long_desc: str
    publisher: str


class SMDHFlags(NamedTuple):
    Visible: bool
    """Icon is visible at the HOME Menu"""

    AutoBoot: bool
    """Auto-boot this game card title"""

    Allow3D: bool
    """Title uses 3D (this is only for parental controls, it does not actually disable 3D if this flag is not set)"""

    RequireEULA: bool
    """Require accepting the EULA before being launched from the HOME Menu"""

    AutoSave: bool
    """Title auto-saves on exit (this means there will not be a prompt to save when attempting to close)"""

    ExtendedBanner: bool
    """Title uses an extended banner"""

    RatingRequired: bool
    """Region-specific game rating required"""

    SaveData: bool
    """Title uses save data (this will prompt the user that unsaved data will be lost, unless AutoSave is set)"""

    RecordUsage: bool
    """Application usage is recorded (when not set, the icon is not stored in the icon cache)"""

    NoSaveBackups: bool
    """Disable Save-Data Backup"""

    New3DS: bool
    """Exclusive to New Nintendo 3DS"""

    @classmethod
    def from_bytes(cls, flag_bytes: bytes):
        flags = int.from_bytes(flag_bytes, 'little')
        return cls(Visible=bool(flags & 0x1),
                   AutoBoot=bool(flags & 0x2),
                   Allow3D=bool(flags & 0x4),
                   RequireEULA=bool(flags & 0x8),
                   AutoSave=bool(flags & 0x10),
                   ExtendedBanner=bool(flags & 0x20),
                   RatingRequired=bool(flags & 0x40),
                   SaveData=bool(flags & 0x80),
                   RecordUsage=bool(flags & 0x100),
                   NoSaveBackups=bool(flags & 0x400),
                   New3DS=bool(flags & 0x1000))


# Based on:
# https://github.com/Steveice10/FBI/blob/c6d92d86b27aaef784d1ecb4103e1346fb0f8a12/source/core/screen.c#L211-L221
def next_pow_2(i: int):
    i -= 1
    i |= i >> 1
    i |= i >> 2
    i |= i >> 4
    i |= i >> 8
    i |= i >> 16
    i += 1

    return i


def rgb565_to_rgb888(data: bytes):
    n = int.from_bytes(data, 'little')
    r = (((n >> 11) & 0x1F) * 0xFF // 0x1F) & 0xFF
    g = (((n >> 5) & 0x3F) * 0xFF // 0x3F) & 0xFF
    b = ((n & 0x1F) * 0xFF // 0x1F) & 0xFF
    return pack('>BBB', r, g, b)


# Based on:
# https://github.com/Steveice10/FBI/blob/c6d92d86b27aaef784d1ecb4103e1346fb0f8a12/source/core/screen.c#L305-L323
def load_tiled_rgb565(data: bytes, width: int, height: int):
    pixel_size = len(data) // width // height

    pixels = []

    for x in range(width):
        for y in range(height):
            pixel_offset = ((((y >> 3) * (width >> 3) + (x >> 3)) << 6) + ((x & 1) | ((y & 1) << 1) | ((x & 2) << 1) | ((y & 2) << 2) | ((x & 4) << 2) | ((y & 4) << 3))) * pixel_size

            pixel = rgb565_to_rgb888(data[pixel_offset:pixel_offset + pixel_size])

            pixels.append(pixel)

    img = Image.frombytes('RGB', (width, height), b''.join(pixels))
    return img.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_90)


class SMDH:
    """
    Class for 3DS SMDH.

    https://www.3dbrew.org/wiki/SMDH
    """

    # TODO: support other settings

    def __init__(self, names: 'Dict[str, AppTitle]', icon_small: 'Image', icon_large: 'Image', flags: SMDHFlags):
        self.names: Mapping[str, AppTitle] = MappingProxyType({n: names.get(n, None) for n in region_names})
        self.icon_small = icon_small
        self.icon_large = icon_large
        self.flags = flags

    def __repr__(self):
        return f'<{type(self).__name__} title: {self.get_app_title().short_desc}>'

    def get_app_title(self, language: 'Union[str, Tuple[str, ...]]' = _region_order_check) -> 'Optional[AppTitle]':
        if isinstance(language, str):
            language = (language,)

        for l in language:
            apptitle = self.names[l]
            if apptitle:
                return apptitle

        # if, for some reason, it fails to return...
        return AppTitle('unknown', 'unknown', 'unknown')

    @classmethod
    def load(cls, fp: 'BinaryIO') -> 'SMDH':
        """Load an SMDH from a file-like object."""
        smdh = fp.read(SMDH_SIZE)
        if len(smdh) != SMDH_SIZE:
            raise InvalidSMDHError(f'invalid size (expected: {SMDH_SIZE:#6x}, got: {len(smdh):#6x}')
        if smdh[0:4] != b'SMDH':
            raise InvalidSMDHError('SMDH magic not found')

        app_structs = smdh[8:0x2008]
        names: Dict[str, AppTitle] = {}
        # due to region_names only being 12 elements, this will only process 12. the other 4 are unused.
        for app_title, region in zip((app_structs[x:x + 0x200] for x in range(0, 0x2000, 0x200)), region_names):
            names[region] = AppTitle(app_title[0:0x80].decode('utf-16le').strip('\0'),
                                     app_title[0x80:0x180].decode('utf-16le').strip('\0'),
                                     app_title[0x180:0x200].decode('utf-16le').strip('\0'))

        icon_raw_small = smdh[0x2040:0x24C0]
        icon_raw_large = smdh[0x24C0:0x36C0]
        # This is assuming icon data is RGB565, but 3dbrew says other formats are possible. Though every known example
        # uses RGB565 and there doesn't seem to be a way to tell which one is being used.
        icon_small = load_tiled_rgb565(icon_raw_small, 24, 24)
        icon_large = load_tiled_rgb565(icon_raw_large, 48, 48)

        flags_raw = smdh[0x2028:0x202C]
        flags = SMDHFlags.from_bytes(flags_raw)

        return cls(names, icon_small, icon_large, flags)

    @classmethod
    def from_file(cls, fn: 'Union[PathLike, str, bytes]') -> 'SMDH':
        with open(fn, 'rb') as f:
            return cls.load(f)
