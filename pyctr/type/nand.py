# This file is a part of pyctr.
#
# Copyright (c) 2017-2020 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from os import PathLike
from threading import Lock
from typing import TYPE_CHECKING

from ..common import PyCTRError
from ..crypto import CryptoEngine
from ..util import readle
from .base.typereader import TypeReaderCryptoBase

if TYPE_CHECKING:
    from typing import BinaryIO, Union

NAND_MEDIA_UNIT = 0x200


class NANDError(PyCTRError):
    """Generic error for NAND operations."""


class InvalidNANDError(NANDError):
    """Invalid NAND header exception."""


class NAND(TypeReaderCryptoBase):
    def __init__(self, file: 'Union[PathLike, str, bytes, BinaryIO]', *, closefd: bool = True,
                 crypto: CryptoEngine = None, dev: bool = False, otp: bytes = None,
                 otp_file: 'Union[PathLike, str, bytes]' = None):
        super().__init__(file=file, closefd=closefd, crypto=crypto, dev=dev)

        self._lock = Lock()

        # set up otp if it was provided
        # otherwise it has to be in essential.exefs or set up manually with a custom CryptoEngine object
        if otp:
            self._crypto.setup_keys_from_otp(otp)
        elif otp_file:
            self._crypto.setup_keys_from_otp_file(otp_file)

        # ignore the signature, we don't need it
        self._file.seek(0x100, 1)
        header = self._file.read(0x100)
        if header[0:4] != b'NCSD':
            raise InvalidNANDError('NCSD magic not found')

        # make sure the Media ID is all zeros, since anything else makes it a CCI
        media_id = header[0x8:0x10]
        if media_id != b'\0' * 8:
            raise InvalidNANDError('Not a NAND, this is a CCI')
