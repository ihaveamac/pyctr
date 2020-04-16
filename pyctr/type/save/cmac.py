# This file is a part of pyctr.
#
# Copyright (c) 2017-2020 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from hashlib import sha256
from typing import TYPE_CHECKING

from ...common import PyCTRError
from ...crypto import Keyslot

if TYPE_CHECKING:
    from typing import List

    from ...crypto import CryptoEngine


class CMACError(PyCTRError):
    """Generic error for CMAC operations."""


class InvalidDataError(CMACError):
    """Not all the data was provided in the correct form."""


def disa_to_sav0_digest(disa: bytes):
    if len(disa) != 0x100:
        raise InvalidDataError(f'DISA header is not 0x100 bytes, got {hex(len(disa))}')

    if disa[0:4] != b'DISA':
        raise InvalidDataError(f'DISA magic not found, got {disa[0:4]}')

    cmac_data = [b'CTR-SAV0', disa]
    return sha256(b''.join(cmac_data)).digest()


class CMACTypeBase:
    """
    Base class for AES-CMAC types.
    """

    def __init__(self, magic: bytes, keyslot: 'Keyslot', *, crypto: 'CryptoEngine' = None):
        self.magic = magic
        self.keyslot = keyslot
        self.crypto = crypto

    def set_crypto(self, crypto: 'CryptoEngine'):
        if not self.crypto:
            self.crypto = crypto

    def generate_cmac(self, header: bytes):
        raise NotImplementedError

    def _gen_cmac_internal(self, data: 'List[bytes]'):
        all_data = [self.magic] + data
        cipher = self.crypto.create_cmac_object(self.keyslot)
        cipher.update(sha256(b''.join(all_data)).digest())
        return cipher.digest()


class CTR_NOR0(CMACTypeBase):
    """
    Used for gamecard saves.

    This isn't well tested since I don't have much experience with gamecard saves.
    """

    def __init__(self, new3ds: bool = False, *, crypto: 'CryptoEngine' = None):
        super().__init__(b'CTR-NOR0', Keyslot.CMACCardSaveNew if new3ds else Keyslot.CMACCardSave, crypto=crypto)

    def generate_cmac(self, disa: bytes):
        return self._gen_cmac_internal([disa_to_sav0_digest(disa)])


class CTR_SIGN(CMACTypeBase):
    """Used for SD savegames."""

    def __init__(self, title_id: bytes, *, crypto: 'CryptoEngine' = None):
        super().__init__(b'CTR-SIGN', Keyslot.CMACSDNAND, crypto=crypto)
        self.title_id = title_id

    def generate_cmac(self, disa: bytes):
        return self._gen_cmac_internal([self.title_id, disa_to_sav0_digest(disa)])


class CTR_SYS0(CMACTypeBase):
    """Used for system savedata."""

    def __init__(self, save_id: bytes, *, crypto: 'CryptoEngine' = None):
        super().__init__(b'CTR-SYS0', Keyslot.CMACSDNAND, crypto=crypto)
        self.save_id = save_id

    def generate_cmac(self, disa: bytes):
        return self._gen_cmac_internal([self.save_id, disa])


class CTR_EXT0(CMACTypeBase):
    """Used for extdata."""

    def __init__(self, extdata_id: bytes, is_quota: bool, device_file_name_id: int = 0,
                 device_directory_name_id: int = 0, *, crypto: 'CryptoEngine' = None):
        super().__init__(b'CTR-EXT0', Keyslot.CMACSDNAND, crypto=crypto)
        self.extdata_id = extdata_id
        self.is_quota = is_quota.to_bytes(4, 'little')
        self.device_file_name_id = device_file_name_id.to_bytes(4, 'little')
        self.device_directory_name_id = device_directory_name_id.to_bytes(4, 'little')

    def generate_cmac(self, diff: bytes):
        return self._gen_cmac_internal([self.extdata_id, self.is_quota, self.device_file_name_id,
                                        self.device_directory_name_id, diff])


class CTR_9DB0(CMACTypeBase):
    """Used for title databases."""

    def __init__(self, database_id: int, is_nand: bool, *, crypto: 'CryptoEngine' = None):
        super().__init__(b'CTR-9DB0', Keyslot.CMACNANDDB if is_nand else Keyslot.CMACSDNAND, crypto=crypto)
        self.database_id = database_id.to_bytes(4, 'little')

    def generate_cmac(self, diff: bytes):
        return self._gen_cmac_internal([self.database_id, diff])
