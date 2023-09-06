# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

"""Provides various tools to perform cryptographic operations with Nintendo 3DS data."""
import logging
from enum import IntEnum
from functools import wraps
from hashlib import sha256
from io import RawIOBase, BytesIO
from os import environ
from os.path import getsize, join as pjoin
from struct import pack, unpack
from threading import Lock
from typing import TYPE_CHECKING

from Cryptodome.Cipher import AES
from Cryptodome.Hash import CMAC
from Cryptodome.Util import Counter

from ..common import PyCTRError, _raise_if_file_closed
from ..util import config_dirs, readbe, readle

if TYPE_CHECKING:
    # noinspection PyProtectedMember
    from Cryptodome.Cipher._mode_cbc import CbcMode
    # noinspection PyProtectedMember
    from Cryptodome.Cipher._mode_ctr import CtrMode
    # noinspection PyProtectedMember
    from Cryptodome.Cipher._mode_ecb import EcbMode
    from Cryptodome.Hash.CMAC import CMAC as CMAC_CLASS
    from typing import BinaryIO, Dict, List, Optional, Union
    from ..common import FilePath

    # trick type checkers
    RawIOBase = BinaryIO

__all__ = ['MIN_TICKET_SIZE', 'CryptoError', 'OTPLengthError', 'CorruptBootromError', 'KeyslotMissingError',
           'TicketLengthError', 'BootromNotFoundError', 'CorruptOTPError', 'Keyslot', 'CryptoEngine', 'CTRFileIO',
           'TWLCTRFileIO', 'CBCFileIO']

logger = logging.getLogger(__name__)

BOOT9_PROT_HASH = '7331f7edece3dd33f2ab4bd0b3a5d607229fd19212c10b734cedcaf78c1a7b98'

DEV_COMMON_KEY_0 = bytes.fromhex('55A3F872BDC80C555A654381139E153B')

MIN_TICKET_SIZE = 0x2AC

OTP_MAGIC = b'\x0f\xb0\xad\xde'


class CryptoError(PyCTRError):
    """Generic exception for cryptography operations."""


class OTPLengthError(CryptoError):
    """OTP is the wrong length."""


class CorruptOTPError(CryptoError):
    """OTP hash does not match."""


class KeyslotMissingError(CryptoError):
    """Normal key is not set up for the keyslot."""


class BadMovableSedError(CryptoError):
    """movable.sed provided is invalid."""


class TicketLengthError(CryptoError):
    """Ticket is too small."""
    def __init__(self, length):
        super().__init__(length)

    def __str__(self):
        return f'0x350 expected, {hex(self.args[0])} given'


# wonder if I'm doing this right...
class BootromNotFoundError(CryptoError):
    """ARM9 bootROM was not found. Main argument is a tuple of checked paths."""


class CorruptBootromError(CryptoError):
    """ARM9 bootROM hash does not match."""


class Keyslot(IntEnum):
    """
    AES engine keyslots used by the Nintendo 3DS. Values above 0x3F (63) are used by PyCTR, and do not exist on the
    actual hardware. Each value explains what the keyslot is used to decrypt or encrypt.
    """

    TWLNAND = 0x03
    """Entire TWL region, including twln, twlp, and the header."""

    CTRNANDOld = 0x04
    """CTRNAND for Old Nintendo 3DS."""
    CTRNANDNew = 0x05
    """CTRNAND for New Nintendo 3DS."""
    FIRM = 0x06
    """FIRM partitions."""
    AGB = 0x07
    """AGBSAVE partition if a GBA VC title was played."""

    CMACNANDDB = 0x0B
    """CMAC for NAND dbs."""

    NCCH93 = 0x18
    """NCCH extra keyslot for titles exclusive to New Nintendo 3DS released after System Menu 9.3.0-21."""
    CMACCardSaveNew = 0x19
    CardSaveNew = 0x1A
    NCCH96 = 0x1B
    """NCCH extra keyslot for titles exclusive to New Nintendo 3DS released after System Menu 9.6.0-24."""

    CMACAGB = 0x24
    """CMAC for the AGBSAVE partition contents."""
    NCCH70 = 0x25
    """NCCH extra keyslot for titles released after System Menu 7.0.0-13."""

    NCCH = 0x2C
    """NCCH original keyslot."""
    UDSLocalWLAN = 0x2D
    StreetPass = 0x2E
    Save60 = 0x2F
    """Save key for retail games released after System Menu 6.0.0-11."""
    CMACSDNAND = 0x30

    CMACCardSave = 0x33
    SD = 0x34
    """SD card contents under "Nintendo 3DS"."""

    CardSave = 0x37
    BOSS = 0x38
    """Used to encrypt SpotPass data."""
    DownloadPlay = 0x39

    DSiWareExport = 0x3A
    """Used when exporting DSiWare to the SD card."""

    CommonKey = 0x3D
    """Titlekeys in tickets."""

    Boot9Internal = 0x3F
    """
    Used for internal operations in the ARM9 BootROM, including decrypting OTP, FIRM sections from non-NAND sources,
    and generating console-unique keys.
    """

    # anything after 0x3F is custom to PyCTR
    DecryptedTitlekey = 0x40
    """CIA and CDN contents."""

    ZeroKey = 0x41
    """All zero key for NCCH titles using fixed crypto."""

    FixedSystemKey = 0x42
    """Special key for NCCH system titles using fixed crypto."""

    New3DSKeySector = 0x43
    """Used to decrypt the secret key sector (sector 0x96) for the New Nintendo 3DS."""

    NCCHExtraKey = 0x44
    """
    Stores a version of another keyslot used for NCCH titles. For titles without a seed, KeyY is taken from the NCCH
    header. For titles with a seed, KeyY is seeded. KeyX is always the same as the source keyslot.
    """


common_key_y = (
    # eShop
    0xD07B337F9CA4385932A2E25723232EB9,
    # System
    0x0C767230F0998F1C46828202FAACBE4C,
    # Unknown
    0xC475CB3AB8C788BB575E12A10907B8A4,
    # Unknown
    0xE486EEE3D0C09C902F6686D4C06F649F,
    # Unknown
    0xED31BA9C04B067506C4497A35B7804FC,
    # Unknown
    0x5E66998AB4E8931606850FD7A16DD755
)

base_key_x = {
    # New3DS 9.3 NCCH
    0x18: (0x82E9C9BEBFB8BDB875ECC0A07D474374, 0x304BF1468372EE64115EBD4093D84276),
    # New3DS 9.6 NCCH
    0x1B: (0x45AD04953992C7C893724A9A7BCE6182, 0x6C8B2944A0726035F941DFC018524FB6),
    # 7x NCCH
    0x25: (0xCEE7D8AB30C00DAE850EF5E382AC5AF3, 0x81907A4B6F1B47323A677974CE4AD71B),
}

# global values to be copied to new CryptoEngine instances after the first one
_b9_key_x: 'Dict[int, int]' = {}
_b9_key_y: 'Dict[int, int]' = {}
_b9_key_normal: 'Dict[int, bytes]' = {}
_b9_extdata_otp: bytes = None
_b9_extdata_keygen: bytes = None
_b9_path: str = None
_otp_key: bytes = None
_otp_iv: bytes = None

b9_paths: 'List[str]' = []
for p in config_dirs:
    b9_paths.append(pjoin(p, 'boot9.bin'))
    b9_paths.append(pjoin(p, 'boot9_prot.bin'))
try:
    b9_paths.insert(0, environ['BOOT9_PATH'])
except KeyError:
    pass


def _requires_bootrom(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        if not self.b9_keys_set:
            raise KeyslotMissingError('bootrom is required to set up keys, see setup_keys_from_boot9')
        return method(self, *args, **kwargs)
    return wrapper


def _requires_otp(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        if not self.b9_keys_set:
            raise KeyslotMissingError('an OTP dump is required, see setup_keys_from_otp')
        return method(self, *args, **kwargs)
    return wrapper


if TYPE_CHECKING:
    def _requires_bootrom(method):
        return method

    def _requires_otp(method):
        return method


# used from http://www.falatic.com/index.php/108/python-and-bitwise-rotation
# converted to def because pycodestyle complained to me
def rol(val: int, r_bits: int, max_bits: int) -> int:
    return (val << r_bits % max_bits) & (2 ** max_bits - 1) |\
           ((val & (2 ** max_bits - 1)) >> (max_bits - (r_bits % max_bits)))


class _TWLCryptoWrapper:
    def __init__(self, cipher: 'CbcMode'):
        self._cipher = cipher

    def encrypt(self, data: bytes) -> bytes:
        data_len = len(data)
        data_rev = bytearray(data_len)
        for i in range(0, data_len, 0x10):
            data_rev[i:i + 0x10] = data[i:i + 0x10][::-1]

        data_out = bytearray(self._cipher.encrypt(bytes(data_rev)))

        for i in range(0, data_len, 0x10):
            data_out[i:i + 0x10] = data_out[i:i + 0x10][::-1]
        return bytes(data_out[0:data_len])

    decrypt = encrypt


class CryptoEngine:
    """
    Emulates the AES engine of the Nintendo 3DS, including keyslots and the key scrambler.

    :param boot9: Path to a dump of the protected region of the ARM9 BootROM. Defaults to None, which causes it to
        search a predefined list of paths.
    :param dev: Whether to use devunit keys.
    :param setup_b9_keys: Whether to automatically load keys from boot9.
    """

    __slots__ = ['key_x', 'key_y', 'key_normal', 'dev', 'b9_keys_set', 'b9_path', 'otp_keys_set', '_otp_enc',
                 '_otp_dec', '_b9_extdata_otp', '_b9_extdata_keygen', '_otp_device_id', '_otp_key', '_otp_iv', '_id0']

    b9_keys_set: bool
    """Keys have been set from the ARM9 BootROM."""

    otp_keys_set: bool
    """Keys have been set from a dumped OTP region."""

    b9_path: 'Optional[str]'
    """
    Path that the ARM9 BootROM was loaded from. Set when :meth:`setup_keys_from_boot9_file` is called, which is
    automatically called on object creation if `setup_b9_keys` was `True`.
    """

    dev: bool
    """Uses devunit keys."""

    def __init__(self, boot9: str = None, dev: bool = False, setup_b9_keys: bool = True):
        self.key_x: Dict[int, int] = {}
        self.key_y: Dict[int, int] = {}
        self.key_normal: Dict[int, bytes] = {}

        self.dev = dev

        self.b9_keys_set = False
        self.b9_path = None

        self.otp_keys_set = False

        self._b9_extdata_otp: Optional[bytes] = None
        self._b9_extdata_keygen: Optional[bytes] = None

        self._otp_device_id: Optional[int] = None
        self._otp_key: Optional[bytes] = None
        self._otp_iv: Optional[bytes] = None

        self._otp_enc: Optional[bytes] = None
        self._otp_dec: Optional[bytes] = None

        self._id0: Optional[bytes] = None

        for keyslot, keys in base_key_x.items():
            self.key_x[keyslot] = keys[dev]

        if setup_b9_keys:
            self.setup_keys_from_boot9_file(boot9)

    @property
    @_requires_bootrom
    def b9_extdata_otp(self) -> bytes:
        return self._b9_extdata_otp

    @property
    @_requires_bootrom
    def b9_extdata_keygen(self) -> bytes:
        return self._b9_extdata_keygen

    @property
    @_requires_bootrom
    def otp_key(self) -> bytes:
        return self._otp_key

    @property
    @_requires_bootrom
    def otp_iv(self) -> bytes:
        return self._otp_iv

    @property
    @_requires_otp
    def otp_device_id(self) -> int:
        return self._otp_device_id

    @property
    @_requires_otp
    def otp_dec(self) -> bytes:
        return self._otp_dec

    @property
    @_requires_otp
    def otp_enc(self) -> bytes:
        return self._otp_enc

    @property
    def id0(self) -> bytes:
        """
        ID0 generated from a ``movable.sed``. One must be loaded first with :func:`setup_sd_key`
        or :func:`setup_sd_key_from_file`.
        """
        if not self._id0:
            raise KeyslotMissingError('load a movable.sed with setup_sd_key')
        return self._id0

    def create_cbc_cipher(self, keyslot: Keyslot, iv: bytes) -> 'CbcMode':
        """
        Create AES-CBC cipher with the given keyslot.

        :param keyslot: :class:`Keyslot` to use.
        :param iv: Initialization vector.
        :return: An AES-CBC cipher object from PyCryptodome.
        :rtype: CbcMode
        """
        try:
            key = self.key_normal[keyslot]
        except KeyError:
            raise KeyslotMissingError(f'normal key for keyslot 0x{keyslot:02x} is not set up')

        return AES.new(key, AES.MODE_CBC, iv)

    def create_ctr_cipher(self, keyslot: Keyslot, ctr: int) -> 'Union[CtrMode, _TWLCryptoWrapper]':
        """
        Create an AES-CTR cipher with the given keyslot.

        Normal and DSi crypto will be automatically chosen depending on keyslot.

        :param keyslot: :class:`Keyslot` to use.
        :param ctr: Counter to start with.
        :return: An AES-CTR cipher object from PyCryptodome, or a wrapper for DSi keyslots.
        :rtype: CtrMode | _TWLCryptoWrapper
        """
        try:
            key = self.key_normal[keyslot]
        except KeyError:
            raise KeyslotMissingError(f'normal key for keyslot 0x{keyslot:02x} is not set up')

        cipher = AES.new(key, AES.MODE_CTR, counter=Counter.new(128, initial_value=ctr))

        if keyslot < 0x04:
            return _TWLCryptoWrapper(cipher)
        else:
            return cipher

    def create_ecb_cipher(self, keyslot: Keyslot) -> 'EcbMode':
        """
        Create an AES-ECB cipher with the given keyslot.

        :param keyslot: :class:`Keyslot` to use.
        :return: An AES-ECB cipher object from PyCryptodome.
        :rtype: EcbMode
        """
        try:
            key = self.key_normal[keyslot]
        except KeyError:
            raise KeyslotMissingError(f'normal key for keyslot 0x{keyslot:02x} is not set up')

        return AES.new(key, AES.MODE_ECB)

    def create_cmac_object(self, keyslot: Keyslot) -> 'CMAC_CLASS':
        """
        Create a CMAC object with the given keyslot.

        :param keyslot: :class:`Keyslot` to use.
        :return: A CMAC object from PyCryptodome.
        :rtype: CMAC
        """
        try:
            key = self.key_normal[keyslot]
        except KeyError:
            raise KeyslotMissingError(f'normal key for keyslot 0x{keyslot:02x} is not set up')

        return CMAC.new(key, ciphermod=AES)

    def create_ctr_io(self, keyslot: Keyslot, fh: 'BinaryIO', ctr: int, closefd: bool = False):
        """
        Create an AES-CTR read-write file object with the given keyslot.

        :param keyslot: :class:`Keyslot` to use.
        :param fh: File-like object to wrap.
        :param ctr: Counter to start with.
        :param closefd: Close underlying file object when closed.
        :return: A file-like object that does decryption and encryption on the fly.
        :rtype: CTRFileIO
        """
        if keyslot < 0x04:
            return TWLCTRFileIO(file=fh,
                                crypto=self,
                                keyslot=keyslot,
                                counter=ctr,
                                closefd=True)
        else:
            return CTRFileIO(file=fh,
                             crypto=self,
                             keyslot=keyslot,
                             counter=ctr,
                             closefd=closefd)

    def create_cbc_io(self, keyslot: Keyslot, fh: 'BinaryIO', iv: bytes, closefd: bool = False):
        """
        Create an AES-CBC read-only file object with the given keyslot.

        :param keyslot: :class:`Keyslot` to use.
        :param fh: File-like object to wrap.
        :param iv: Initialization vector.
        :param closefd: Close underlying file object when closed.
        :return: A file-like object that does decryption on the fly.
        :rtype: CBCFileIO
        """
        return CBCFileIO(file=fh,
                         crypto=self,
                         keyslot=keyslot,
                         iv=iv,
                         closefd=closefd)

    @staticmethod
    def sd_path_to_iv(path: str) -> int:
        """
        Generate an IV from an SD file path relevant to the root of an ID1 directory (e.g.
        `/title/00040000/0f70c600/content/00000000.app`). Both Unix- and Windows-style paths are accepted.

        :param path: SD file path.
        :return: IV as an integer.
        """
        # ensure the path is lowercase
        path = path.lower()
        # allow Windows-style paths to be passed in
        path = path.replace('\\', '/')

        # SD Save Data Backup does a copy of the raw, encrypted file from the game's data directory
        # so we need to handle this and fake the path
        if path.startswith('/backup') and len(path) > 28:
            tid_upper = path[12:20]
            tid_lower = path[20:28]
            path = f'/title/{tid_upper}/{tid_lower}/data' + path[28:]

        path_hash = sha256(path.encode('utf-16le') + b'\0\0').digest()
        hash_p1 = readbe(path_hash[0:16])
        hash_p2 = readbe(path_hash[16:32])
        return hash_p1 ^ hash_p2

    def load_encrypted_titlekey(self, titlekey: bytes, common_key_index: int, title_id: 'Union[str, bytes]'):
        """
        Decrypt an encrypted titlekey and store in keyslot 0x40 (:attr:`Keyslot.DecryptedTitlekey`).

        :param titlekey: Encrypted titlekey
        :param common_key_index: Common key Y to use. 0 for eShop, 1 for System.
        :param title_id: Title ID.
        """
        if isinstance(title_id, str):
            title_id = bytes.fromhex(title_id)

        if self.dev and common_key_index == 0:
            self.set_normal_key(Keyslot.CommonKey, DEV_COMMON_KEY_0)
        else:
            self.set_keyslot('y', Keyslot.CommonKey, common_key_y[common_key_index])

        cipher = self.create_cbc_cipher(Keyslot.CommonKey, title_id + (b'\0' * 8))
        self.set_normal_key(Keyslot.DecryptedTitlekey, cipher.decrypt(titlekey))

    def load_from_ticket(self, ticket: bytes):
        """Load a titlekey from a ticket and set keyslot 0x40 to the decrypted titlekey."""
        ticket_len = len(ticket)
        # TODO: probably support other sig types which would be different lengths
        # unlikely to happen in practice, but I would still like to
        if ticket_len < 0x2AC:
            raise TicketLengthError(ticket_len)

        titlekey_enc = ticket[0x1BF:0x1CF]
        title_id = ticket[0x1DC:0x1E4]
        common_key_index = ticket[0x1F1]

        self.load_encrypted_titlekey(titlekey_enc, common_key_index, title_id)

    def set_keyslot(self, xy: str, keyslot: int, key: 'Union[int, bytes]'):
        """Sets a keyslot to the specified key."""
        to_use = None
        if xy == 'x':
            to_use = self.key_x
        elif xy == 'y':
            to_use = self.key_y
        if isinstance(key, bytes):
            key = int.from_bytes(key, 'big' if keyslot > 0x03 else 'little')
        if __debug__:
            logger.debug('Setting keyslot %r type %s key %032x', keyslot, xy, key)
        to_use[keyslot] = key
        try:
            self.key_normal[keyslot] = self.keygen(keyslot)
        except KeyError:
            pass

    def set_normal_key(self, keyslot: int, key: bytes):
        """
        Set the normal key for a keyslot.

        :param keyslot: Keyslot to set normal key of.
        :param key: 128-bit AES key in bytes.
        """
        if __debug__:
            logger.debug('Setting keyslot %r type normal key %s', keyslot, key.hex())
        self.key_normal[keyslot] = key

    def keygen(self, keyslot: int) -> bytes:
        """
        Generate a normal key based on the KeyX and KeyY for the keyslot.

        :param keyslot: Keyslot to load KeyX and KeyY from.
        :return: Generated normal key.
        :rtype: bytes
        """
        if keyslot < 0x04:
            # DSi
            return self.keygen_twl_manual(self.key_x[keyslot], self.key_y[keyslot])
        else:
            # 3DS
            return self.keygen_manual(self.key_x[keyslot], self.key_y[keyslot])

    @staticmethod
    def keygen_manual(key_x: int, key_y: int) -> bytes:
        """Generate a normal key using the 3DS AES key scrambler."""
        return rol((rol(key_x, 2, 128) ^ key_y) + 0x1FF9E9AAC5FE0408024591DC5D52768A, 87, 128).to_bytes(0x10, 'big')

    @staticmethod
    def keygen_twl_manual(key_x: int, key_y: int) -> bytes:
        """Generate a normal key using the DSi AES key scrambler."""
        # usually would convert to LE bytes in the end then flip with [::-1], but those just cancel out
        return rol((key_x ^ key_y) + 0xFFFEFB4E295902582A680F5F1A4F3E79, 42, 128).to_bytes(0x10, 'big')

    def _set_fixed_keys(self):
        self.set_keyslot('y', Keyslot.TWLNAND, 0xE1A00005202DDD1DBD4DC4D30AB9DC76)
        self.set_keyslot('y', Keyslot.CTRNANDNew, 0x4D804F4E9990194613A204AC584460BE)
        self.set_normal_key(Keyslot.ZeroKey, b'\0' * 16)
        self.set_normal_key(Keyslot.FixedSystemKey, bytes.fromhex('527CE630A9CA305F3696F3CDE954194B'))

    def _copy_global_keys(self):
        self.key_x.update(_b9_key_x)
        self.key_y.update(_b9_key_y)
        self.key_normal.update(_b9_key_normal)
        self._otp_key = _otp_key
        self._otp_iv = _otp_iv
        self._b9_extdata_otp = _b9_extdata_otp
        self._b9_extdata_keygen = _b9_extdata_keygen

        self._set_fixed_keys()

        self.b9_keys_set = True

    def setup_keys_from_boot9(self, b9: bytes):
        """Set up certain keys from an ARM9 bootROM dump."""
        global _otp_key, _otp_iv, _b9_extdata_otp, _b9_extdata_keygen
        if self.b9_keys_set:
            return

        if _b9_key_x:
            self._copy_global_keys()
            return

        b9_len = len(b9)
        if b9_len != 0x8000:
            raise CorruptBootromError(f'wrong length: {b9_len}')

        b9_hash_digest: str = sha256(b9).hexdigest()
        if b9_hash_digest != BOOT9_PROT_HASH:
            raise CorruptBootromError(f'expected: {BOOT9_PROT_HASH}; returned: {b9_hash_digest}')

        keyblob_offset = 0x5860
        otp_key_offset = 0x56E0
        if self.dev:
            keyblob_offset += 0x400
            otp_key_offset += 0x20

        _otp_key = b9[otp_key_offset:otp_key_offset + 0x10]
        _otp_iv = b9[otp_key_offset + 0x10:otp_key_offset + 0x20]

        keyblob = BytesIO(b9[keyblob_offset:keyblob_offset + 0x400])

        _b9_extdata_keygen = keyblob.read(0x200)
        _b9_extdata_otp = _b9_extdata_keygen[0:0x24]

        # load keys
        # based on https://github.com/yellows8/boot9_tools/blob/7630e679f1409b90bf40939cd78c3b008ebb2761/boot9_keytool.sh

        keyblob.seek(0x170)
        def key_loop(keyslot: int, kdict: 'Dict[int, Union[int, bytes]]', conv_func):
            data = conv_func(keyblob.read(16))
            for i in range(4):
                kdict[keyslot + i] = data

        def key_loop_increase(keyslot: int, kdict: 'Dict[int, Union[int, bytes]]', conv_func):
            for i in range(4):
                data = conv_func(keyblob.read(16))
                kdict[keyslot + i] = data

        key_loop(0x2C, _b9_key_x, readbe)
        key_loop(0x30, _b9_key_x, readbe)
        key_loop(0x34, _b9_key_x, readbe)
        key_loop(0x38, _b9_key_x, readbe)
        key_loop_increase(0x3C, _b9_key_x, readbe)

        key_loop_increase(0x04, _b9_key_y, readbe)
        key_loop_increase(0x08, _b9_key_y, readbe)

        key_loop(0x0C, _b9_key_normal, bytes)
        key_loop(0x10, _b9_key_normal, bytes)
        key_loop_increase(0x14, _b9_key_normal, bytes)
        key_loop(0x18, _b9_key_normal, bytes)
        key_loop(0x1C, _b9_key_normal, bytes)
        key_loop(0x20, _b9_key_normal, bytes)
        key_loop(0x24, _b9_key_normal, bytes)
        keyblob.seek(-16, 1)
        key_loop_increase(0x28, _b9_key_normal, bytes)
        key_loop(0x2C, _b9_key_normal, bytes)
        key_loop(0x30, _b9_key_normal, bytes)
        key_loop(0x34, _b9_key_normal, bytes)
        key_loop(0x38, _b9_key_normal, bytes)
        keyblob.seek(-16, 1)
        key_loop_increase(0x3C, _b9_key_normal, bytes)

        self._copy_global_keys()

    def setup_keys_from_boot9_file(self, path: 'FilePath' = None):
        """Set up certain keys from an ARM9 bootROM file."""
        global _b9_path
        if self.b9_keys_set:
            return

        if _b9_key_x:
            self.b9_path = _b9_path
            self._copy_global_keys()
            return

        paths = (path,) if path else b9_paths

        for p in paths:
            try:
                b9_size = getsize(p)
                if b9_size in {0x8000, 0x10000}:
                    with open(p, 'rb') as f:
                        if b9_size == 0x10000:
                            f.seek(0x8000)
                        self.setup_keys_from_boot9(f.read(0x8000))
                        _b9_path = p
                        self.b9_path = p
                        return
            except FileNotFoundError:
                continue

        # if keys are not set...
        raise BootromNotFoundError(paths)

    @_requires_bootrom
    def setup_keys_from_otp(self, otp: bytes):
        """
        Set up console-unique keys from an OTP dump. Encrypted and decrypted are supported.

        :param otp: OTP data, encrypted or decrypted.
        """
        otp_len = len(otp)
        if otp_len != 0x100:
            raise OTPLengthError(otp_len)

        cipher_otp = AES.new(self.otp_key, AES.MODE_CBC, self.otp_iv)
        if otp[0:4] == OTP_MAGIC:
            # decrypted otp
            self._otp_enc: bytes = cipher_otp.encrypt(otp)
            self._otp_dec = otp
        else:
            # encrypted otp
            self._otp_enc = otp
            self._otp_dec: bytes = cipher_otp.decrypt(otp)
        
        if self._otp_dec[0:4] != OTP_MAGIC:
            raise CorruptOTPError('OTP magic not found, corrupt or not an OTP')

        self._otp_device_id = int.from_bytes(self.otp_dec[4:8], 'little')

        otp_hash: bytes = self.otp_dec[0xE0:0x100]
        otp_hash_digest: bytes = sha256(self.otp_dec[0:0xE0]).digest()
        if otp_hash_digest != otp_hash:
            raise CorruptOTPError(f'expected: {otp_hash.hex()}; result: {otp_hash_digest.hex()}')

        otp_keysect_hash: bytes = sha256(self.otp_enc[0:0x90]).digest()

        self.set_keyslot('x', Keyslot.New3DSKeySector, otp_keysect_hash[0:0x10])
        self.set_keyslot('y', Keyslot.New3DSKeySector, otp_keysect_hash[0x10:0x20])

        # most otp code from https://github.com/Stary2001/3ds_tools/blob/master/three_ds/aesengine.py

        twl_cid_lo, twl_cid_hi = readle(self.otp_dec[0x08:0xC]), readle(self.otp_dec[0xC:0x10])
        twl_cid_lo ^= 0xB358A6AF
        twl_cid_lo |= 0x80000000
        twl_cid_hi ^= 0x08C267B7
        twl_cid_lo = twl_cid_lo.to_bytes(4, 'little')
        twl_cid_hi = twl_cid_hi.to_bytes(4, 'little')
        self.set_keyslot('x', Keyslot.TWLNAND, twl_cid_lo + b'NINTENDO' + twl_cid_hi)

        console_key_xy: bytes = sha256(self.otp_dec[0x90:0xAC] + self.b9_extdata_otp).digest()
        self.set_keyslot('x', Keyslot.Boot9Internal, console_key_xy[0:0x10])
        self.set_keyslot('y', Keyslot.Boot9Internal, console_key_xy[0x10:0x20])

        extdata_off = 0

        def gen(n: int) -> bytes:
            nonlocal extdata_off
            extdata_off += 36
            iv = self.b9_extdata_keygen[extdata_off:extdata_off+16]
            extdata_off += 16

            data = self.create_cbc_cipher(Keyslot.Boot9Internal, iv).encrypt(self.b9_extdata_keygen[extdata_off:extdata_off + 64])

            extdata_off += n
            return data

        a = gen(64)
        for i in range(0x4, 0x8):
            self.set_keyslot('x', i, a[0:16])

        for i in range(0x8, 0xc):
            self.set_keyslot('x', i, a[16:32])

        for i in range(0xc, 0x10):
            self.set_keyslot('x', i, a[32:48])

        self.set_keyslot('x', 0x10, a[48:64])

        b = gen(16)
        off = 0
        for i in range(0x14, 0x18):
            self.set_keyslot('x', i, b[off:off + 16])
            off += 16

        c = gen(64)
        for i in range(0x18, 0x1c):
            self.set_keyslot('x', i, c[0:16])

        for i in range(0x1c, 0x20):
            self.set_keyslot('x', i, c[16:32])

        for i in range(0x20, 0x24):
            self.set_keyslot('x', i, c[32:48])

        self.set_keyslot('x', Keyslot.CMACAGB, c[48:64])

        d = gen(16)
        off = 0

        for i in range(0x28, 0x2c):
            self.set_keyslot('x', i, d[off:off + 16])
            off += 16

        self.otp_keys_set = True

    @_requires_bootrom
    def setup_keys_from_otp_file(self, path: 'FilePath'):
        """Set up console-unique keys from an OTP file. Encrypted and decrypted are supported."""
        with open(path, 'rb') as f:
            self.setup_keys_from_otp(f.read(0x100))

    def setup_sd_key(self, data: bytes):
        """Set up the SD key from movable.sed. Must be 0x10 (only key), 0x120 (no cmac), or 0x140 (with cmac)."""
        if len(data) == 0x10:
            key = data
        elif len(data) in {0x120, 0x140}:
            key = data[0x110:0x120]
        else:
            raise BadMovableSedError(f'invalid length ({hex(len(data))}')

        self.set_keyslot('y', Keyslot.SD, key)
        self.set_keyslot('y', Keyslot.CMACSDNAND, key)
        self.set_keyslot('y', Keyslot.DSiWareExport, key)

        key_hash = sha256(key).digest()[0:16]
        hash_parts = unpack('<IIII', key_hash)
        self._id0 = pack('>IIII', *hash_parts)

    def setup_sd_key_from_file(self, path: 'FilePath'):
        """Set up the SD key from a movable.sed file."""
        with open(path, 'rb') as f:
            self.setup_sd_key(f.read(0x140))

    def _format_state(self):
        """
        Formats the current state of the engine into Markdown.
        This is for debugging and so is slow and expensive.
        """
        from .. import __version__
        from io import StringIO

        out = StringIO()
        longest_keyslot_name = 0

        def keyslot_repr(ks):
            nonlocal longest_keyslot_name
            try:
                val = Keyslot(ks).name
            except ValueError:
                val = f''
            longest_keyslot_name = len(val) if len(val) > longest_keyslot_name else longest_keyslot_name
            return val

        print('# CryptoEngine state', file=out)
        print('* pyctr version:', __version__, file=out)
        print('* Key set:', 'dev' if self.dev else 'retail', file=out)
        print('* B9 path loaded:', self.b9_path, file=out)
        print('* B9 keys set (local):', self.b9_keys_set, file=out)
        print('* B9 keys set (global):', bool(_b9_key_x), file=out)
        print('* OTP keys set:', self.otp_keys_set, file=out)
        key_x = {}
        key_y = {}
        key_normal = {}
        for ks, v in self.key_x.items():
            key_x[ks] = v.to_bytes(0x10, ('big' if ks > 0x03 else 'little'))
        for ks, v in self.key_y.items():
            key_y[ks] = v.to_bytes(0x10, ('big' if ks > 0x03 else 'little'))
        for ks, v in self.key_normal.items():
            key_normal[ks] = v

        all_keyslots = sorted(key_x.keys() | key_y.keys() | key_normal.keys())
        all_keyslot_names = {x: keyslot_repr(x) for x in all_keyslots}

        print(file=out)
        print(f'| Keyslot | {"Name".ljust(longest_keyslot_name)} | {"X".ljust(34)} | {"Y".ljust(34)} | {"Normal".ljust(34)} | N State |', file=out)
        print(f'| ------- | {"-" * longest_keyslot_name} | {"-" * 34} | {"-" * 34} | {"-" * 34} | ------- |', file=out)
        for ks in all_keyslots:
            try:
                x = '`' + key_x[ks].hex() + '`'
            except KeyError:
                x = '(none)'.ljust(34)
            try:
                y = '`' + key_y[ks].hex() + '`'
            except KeyError:
                y = '(none)'.ljust(34)
            n_state = '       '
            try:
                n = '`' + key_normal[ks].hex() + '`'
            except KeyError:
                n = '(none)'.ljust(34)
            else:
                if ks in key_x and ks in key_y:
                    expected_n = self.keygen(ks)
                    if expected_n.hex() != n:
                        n_state = 'invalid'

            print(f'| 0x{ks:02X}    | {all_keyslot_names[ks].ljust(longest_keyslot_name)} | {x} | {y} | {n} | {n_state} |', file=out)

        return out.getvalue()

    def _print_state(self):
        """
        Prints the current state of the engine.
        This is for debugging and so is slow and expensive.
        """
        print(self._format_state())


class _CryptoFileBase(RawIOBase):
    """Base class for CTR and CBC IO classes."""

    closed = False
    _reader: 'BinaryIO'
    _closefd: bool

    def close(self):
        self.closed = True
        if self._closefd:
            self._reader.close()

    __del__ = close

    @_raise_if_file_closed
    def flush(self):
        self._reader.flush()

    @_raise_if_file_closed
    def tell(self) -> int:
        return self._reader.tell()

    @_raise_if_file_closed
    def readable(self) -> bool:
        return self._reader.readable()

    @_raise_if_file_closed
    def writable(self) -> bool:
        return self._reader.writable()

    @_raise_if_file_closed
    def seekable(self) -> bool:
        return self._reader.seekable()

    @_raise_if_file_closed
    def fileno(self) -> int:
        return self._reader.fileno()


class CTRFileIO(_CryptoFileBase):
    """Provides transparent read-write AES-CTR encryption as a file-like object."""

    def __init__(self, file: 'BinaryIO', crypto: 'CryptoEngine', keyslot: Keyslot, counter: int,
                 closefd: bool = False):
        self._reader = file
        self._crypto = crypto
        self._keyslot = keyslot
        self._counter = counter
        self._closefd = closefd
        self._lock = Lock()

        # attempt to re-use a cipher object when possible (it becomes invalidated when seeking)
        self._current_cipher = None

    def __repr__(self):
        return (f'{type(self).__name__}(file={self._reader!r}, keyslot={self._keyslot}, counter={self._counter!r}, '
                f'closefd={self._closefd!r})')

    def __hash__(self):
        return hash((self._reader, self._keyslot, self._counter, id(self)))

    @_raise_if_file_closed
    def read(self, size: int = -1) -> bytes:
        with self._lock:
            cur_offset = self.tell()
            data = self._reader.read(size)
            cipher = self._current_cipher
            if not cipher:
                counter = self._counter + (cur_offset >> 4)
                cipher = self._crypto.create_ctr_cipher(self._keyslot, counter)
                # beginning padding
                cipher.decrypt(b'\0' * (cur_offset % 0x10))
                self._current_cipher = cipher
            return cipher.decrypt(data)

    @_raise_if_file_closed
    def write(self, data: bytes) -> int:
        with self._lock:
            cur_offset = self.tell()
            cipher = self._current_cipher
            if not cipher:
                counter = self._counter + (cur_offset >> 4)
                cipher = self._crypto.create_ctr_cipher(self._keyslot, counter)
                # beginning padding
                cipher.encrypt(b'\0' * (cur_offset % 0x10))
                self._current_cipher = cipher
            return self._reader.write(cipher.encrypt(data))

    @_raise_if_file_closed
    def seek(self, seek: int, whence: int = 0) -> int:
        # TODO: if the seek goes past the file, the data between the former EOF and seek point should also be encrypted.
        # reset current cipher because it's now invalid
        self._current_cipher = None
        return self._reader.seek(seek, whence)

    def truncate(self, size: 'Optional[int]' = None) -> int:
        return self._reader.truncate(size)


class TWLCTRFileIO(CTRFileIO):
    """Provides transparent read-write TWL AES-CTR encryption as a file-like object."""

    # TWL AES operations need data added at the end too
    # because each 0x10-byte block is flipped before and after it is de/encrypted

    @_raise_if_file_closed
    def read(self, size: int = -1) -> bytes:
        with self._lock:
            cur_offset = self.tell()
            data = self._reader.read(size)
            padding_before = cur_offset % 0x10
            padding_after = (-(padding_before + len(data)) % 0x10)
            counter = self._counter + (cur_offset >> 4)
            cipher = self._crypto.create_ctr_cipher(self._keyslot, counter)
            data = (b'\0' * padding_before) + data + (b'\0' * padding_after)
            return cipher.decrypt(data)[padding_before:len(data) - padding_after]

    @_raise_if_file_closed
    def write(self, data: bytes) -> int:
        with self._lock:
            cur_offset = self.tell()
            padding_before = cur_offset % 0x10
            padding_after = (-(padding_before + len(data)) % 0x10)
            counter = self._counter + (cur_offset >> 4)
            cipher = self._crypto.create_ctr_cipher(self._keyslot, counter)
            data = (b'\0' * padding_before) + data + (b'\0' * padding_after)
            data = cipher.encrypt(data)
            return self._reader.write(data[padding_before:len(data) - padding_after])


class CBCFileIO(_CryptoFileBase):
    """Provides transparent read-only AES-CBC encryption as a file-like object."""

    def __init__(self, file: 'BinaryIO', crypto: 'CryptoEngine', keyslot: Keyslot, iv: bytes, closefd: bool = False):
        self._reader = file
        self._crypto = crypto
        self._keyslot = keyslot
        self._iv = iv
        self._closefd = closefd
        self._lock = Lock()

    def __repr__(self):
        return (f'{type(self).__name__}(file={self._reader!r}, keyslot={self._keyslot}, iv={self._iv!r}, '
                f'closefd={self._closefd!r})')

    def __hash__(self):
        return hash((self._reader, self._keyslot, self._iv, id(self)))

    @_raise_if_file_closed
    def read(self, size: int = -1):
        with self._lock:
            offset = self._reader.tell()

            # if encrypted, the block needs to be decrypted first
            # CBC requires a full block (0x10 in this case). and the previous
            #   block is used as the IV. so that's quite a bit to read if the
            #   application requires just a few bytes.
            # thanks Stary2001 for help with random-access crypto

            before = offset % 16
            if offset - before == 0:
                iv = self._iv
                self._reader.seek(0)
            else:
                # seek back one block to read it as iv
                self._reader.seek(-0x10 - before, 1)
                iv = self._reader.read(0x10)
            # this is done since we may not know the original size of the file
            # and the caller may have requested -1 to read all the remaining data
            data_before = self._reader.read(before)
            data_requested = self._reader.read(size)
            data_requested_len = len(data_requested)
            data_total_len = len(data_before) + data_requested_len
            if data_total_len % 16:
                data_after = self._reader.read(16 - (data_total_len % 16))
                self._reader.seek(-len(data_after), 1)
            else:
                data_after = b''
            cipher = self._crypto.create_cbc_cipher(self._keyslot, iv)
            # decrypt data, and cut off extra bytes
            return cipher.decrypt(
                b''.join((data_before, data_requested, data_after))
            )[before:data_requested_len + before]

    @_raise_if_file_closed
    def seek(self, seek: int, whence: int = 0):
        # even though read re-seeks to read required data, this allows the underlying object to handle seek how it wants
        with self._lock:
            return self._reader.seek(seek, whence)

    @_raise_if_file_closed
    def writable(self) -> bool:
        return False
