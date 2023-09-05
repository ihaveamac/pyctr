# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .common import FilePath


__all__ = ['FileType', 'identify_type']


class FileType(Enum):
    Unknown = 'unknown'
    RomFS = 'romfs'
    ExeFS = 'exefs'
    CCI = 'cci'
    CIA = 'cia'
    CDN = 'cdn'
    SDTitle = 'sdtitle'
    SD = 'sd'
    NCCH = 'ncch'
    SMDH = 'smdh'
    DIFF = 'diff'
    DISA = 'disa'
    NAND = 'nand'
    FIRM = 'firm'
    Ticket = 'ticket'
    TitleMetadata = 'tmd'
    NDS = 'nds'
    ThreeDSX = '3dsx'
    MovableSed = 'movable.sed'

    TMD = TitleMetadata


# these magic values appear at offset 0
MAGICS_0x0 = {
    b'IVFC': FileType.RomFS,
    b'\x28\x00\x00\x00': FileType.RomFS,  # lv3 only
    b'FIRM': FileType.FIRM,
    b'SMDH': FileType.SMDH,
    b'3DSX': FileType.ThreeDSX,
    b'SEED': FileType.MovableSed,
    # hardcoded Archive Header Size, Type, Version, and Certificate chain size
    # but these values are extremely unlikely to change in practice
    bytes.fromhex('20200000 00000000 000A0000'): FileType.CIA
}

# these magic values appear at offset 0x100
MAGICS_0x100 = {
    b'NCCH': FileType.NCCH,
    b'DISA': FileType.DISA,
    b'DIFF': FileType.DIFF,
}

MAGICS_0xC0 = {
    b'\x24\xFF\xAE\x51': FileType.NDS
}


def identify_type(path: 'FilePath') -> FileType:
    p = Path(path).resolve()

    if p.is_file():
        with p.open('rb') as f:
            header = f.read(0x2C0)

        file_magic_0x0 = header[0:4]
        file_magic_0x100 = header[0x100:0x104]

        magics_map = (
            (MAGICS_0x0, 0),
            (MAGICS_0x100, 0x100),
            (MAGICS_0xC0, 0xC0)
        )

        for magics, offset in magics_map:
            for magic, ftype in magics.items():
                file_magic = header[offset:offset + len(magic)]
                if file_magic == magic:
                    return ftype

        # check if an NCSD is a NAND or CCI
        if file_magic_0x100 == b'NCSD':
            # check the Media ID, all zeros is for NAND
            if header[0x108:0x110] == (b'\0' * 8):
                return FileType.NAND
            else:
                return FileType.CCI

        # so detecting this one won't be easy


        return FileType.Unknown

    elif p.is_dir():
        if p.name == 'Nintendo 3DS':
            return FileType.SD

        contents = [x.name for x in p.iterdir()]
        for n in contents:
            if n.endswith('.app'):
                # this should probably check if it's encrypted or not
                return FileType.SDTitle
            if n == 'tmd' or n.startswith('tmd.'):
                return FileType.CDN

    else:
        raise NotImplementedError('not a file but also not a directory?')
