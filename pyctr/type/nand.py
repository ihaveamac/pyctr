# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from enum import IntEnum
from hashlib import sha1, sha256
from logging import getLogger
from struct import Struct, iter_unpack
from threading import Lock
from typing import NamedTuple, TYPE_CHECKING
from weakref import WeakSet

from ..common import PyCTRError
from ..crypto import CryptoEngine, Keyslot
from ..fileio import SubsectionIO
from ..util import readbe, readle
from .base.typereader import TypeReaderCryptoBase
from .exefs import ExeFSReader, InvalidExeFSError, ExeFSFileNotFoundError

if TYPE_CHECKING:
    from typing import Dict, List, Optional, Set, Tuple, Union
    from ..common import FilePath, FilePathOrObject

logger = getLogger(__name__)

NAND_MEDIA_UNIT = 0x200

# ncsd image doesn't have the actual size
nand_size = {0x200000: 0x3AF00000, 0x280000: 0x4D800000}

# for consoles with corrupted twl mbrs
DEFAULT_TWL_MBR_INFO = [(77312, 150688256), (151067136, 34301440), (0, 0), (0, 0)]

EMPTY_BLOCK = b'\0' * 16

NANDNCSDHeaderStruct = Struct('<256s 4s I Q 8s 8s 64s 94s 66s')


class NCSDPartitionInfo(NamedTuple):
    fs_type: 'Union[PartitionFSType, int]'
    encryption_type: 'Union[PartitionEncryptionType, int]'
    offset: int
    size: int
    base_file: 'Optional[str]'


class NANDNCSDHeader(NamedTuple):
    signature: bytes
    """RSA signature over the NAND header."""

    image_size: int
    """Image size according to the NAND header in bytes. This doesn't line up with the actual image size."""

    actual_image_size: int
    """
    Actual image size in bytes. This is the minimum size of a NAND image, but the actual size
    of the backup may be larger.
    """

    partition_table: 'Dict[int, NCSDPartitionInfo]'
    """Partition information. Normally includes 5 partitions, but may include up to 8."""

    unknown: bytes
    """Unknown padding data. This is preserved so the header can be re-built exactly with a valid signature."""

    twl_mbr_encrypted: bytes
    """TWL MBR in its encrypted form."""

    @classmethod
    def from_bytes(cls, data: bytes):
        header = NANDNCSDHeaderStruct.unpack(data)

        magic = header[1]
        image_size_mu = header[2]
        image_size = image_size_mu * NAND_MEDIA_UNIT
        actual_image_size = nand_size[image_size_mu]
        media_id = header[3]

        if magic != b'NCSD':
            raise InvalidNANDError(f'NCSD magic not found (got {header[1]} instead')

        if media_id != 0:
            raise InvalidNANDError(f'Not a NAND, this is a CCI (Media ID {media_id:016x})')

        fs_types = header[4]
        crypt_types = header[5]
        table = iter_unpack('2I', header[6])
        base_file = None

        partitions = {}

        for idx, (fs_type, crypt_type, location) in enumerate(zip(fs_types, crypt_types, table)):
            if not fs_type:  # if there is no partition
                continue

            if fs_type == PartitionFSType.Normal:
                if crypt_type == PartitionEncryptionType.TWL:
                    base_file = 'twl'
                elif crypt_type == PartitionEncryptionType.CTR:
                    base_file = 'ctr_old'
                elif crypt_type == PartitionEncryptionType.New3DSCTR:
                    base_file = 'ctr_new'
            elif fs_type == PartitionFSType.FIRM:
                base_file = 'firm'
            elif fs_type == PartitionFSType.AGBFIRMSave:
                base_file = 'agb'

            info = NCSDPartitionInfo(fs_type=fs_type,
                                     encryption_type=crypt_type,
                                     offset=location[0] * NAND_MEDIA_UNIT,
                                     size=location[1] * NAND_MEDIA_UNIT,
                                     base_file=base_file)

            logger.info('NCSD Partition index %i, fs type %i, encryption type %i, offset %#x, size %#x, base file %s',
                        idx, info.fs_type, info.encryption_type, info.offset, info.size, info.base_file)

            partitions[idx] = info

        return cls(signature=header[0],
                   image_size=image_size,
                   actual_image_size=actual_image_size,
                   partition_table=partitions,
                   unknown=header[7],
                   twl_mbr_encrypted=header[8])


class NANDError(PyCTRError):
    """Generic error for NAND operations."""


class InvalidNANDError(NANDError):
    """Invalid NAND header exception."""


class MissingOTPError(NANDError):
    """OTP wasn't loaded."""


class PartitionFSType(IntEnum):
    """Type of filesystem in the partition."""

    Nothing = 0  # this would be "None" but that's a reserved keyword
    """No partition here."""

    Normal = 1
    """Used for TWL and CTR parts."""

    FIRM = 3
    """Used for FIRM partitions."""

    AGBFIRMSave = 4
    """Used for the AGB_FIRM save partition."""


class PartitionEncryptionType(IntEnum):
    """
    Type of encryption on the partition. In practice this is only really used to determine what keyslot to use for
    CTRNAND which changes between Old 3DS and New 3DS. It's not really known what happens if any of the other partitions
    have the crypt type changed.
    """

    TWL = 1
    """Used for the TWL partitions."""

    CTR = 2
    """Used for FIRM, CTR on Old 3DS, and AGB_FIRM save partitions."""

    New3DSCTR = 3
    """Used for the CTR partitions on New 3DS."""


def parse_mbr_lazy(raw_mbr: bytes):
    """
    Parses a raw MBR header and returns offsets and sizes for each partition.

    :param raw_mbr: The 0x42-byte MBR header.
    :return: A list of tuples indicating offset and size in bytes.
    """
    if len(raw_mbr) != 0x42:
        raise InvalidNANDError(f'invalid mbr size; expected 0x42, got {len(raw_mbr):#0x}')

    mbr_magic = raw_mbr[0x40:0x42]
    if mbr_magic != b'\x55\xAA':
        raise InvalidNANDError(f"invalid mbr magic; expected b'\\x55\\xAA', got {mbr_magic!r}")

    partitions = []

    for idx in range(4):
        entry = raw_mbr[0x10 * idx:0x10 * (idx + 1)]
        offset = int.from_bytes(entry[0x8:0xC], 'little') * 0x200
        size = int.from_bytes(entry[0xC:0x10], 'little') * 0x200
        partitions.append((offset, size))

    return partitions


class NAND(TypeReaderCryptoBase):
    """
    Reads a Nintendo 3DS NAND image.

    If OTP and CID are not provided, it will attempt to load both from essential.exefs.

    If OTP is provided but not CID, it will attempt to generate the Counter for both CTR and TWL.

    :param file: A file path or a file-like object with the CIA data.
    :param mode: Mode to open the file with, passed to `open`. Only used if a file path was given.
    :param closefd: Close the underlying file object when closed. Defaults to `True` for file paths, and `False` for
        file-like objects.
    :param crypto: A custom :class:`~.CryptoEngine` object to be used. Defaults to None, which causes a new one to
        be created.
    :param dev: Use devunit keys.
    :param otp: OTP, used to generate the required encryption keys. Overrides `otp_file` if both are provided.
    :param otp_file: Path to a file containing the OTP.
    :param cid: NAND CID, used to generate the Counter. Overrides `cid_file` if both are provided.
    :param cid_file: Path to a file containing the NAND CID.
    :param auto_raise_exceptions: Automatically raise an exception if the CTR or TWL partitions are inaccessible. This
        calls :func:`raise_if_ctr_failed` and :func:`raise_if_twl_failed` at the end of initialization. Set this to
        `False` if you still need access to a NAND even if these sections are unavailable.
    """

    __slots__ = (
        '_base_files', '_lock', '_subfile', 'counter', 'counter_twl', 'ctr_index', 'ctr_partitions', 'essential',
        'header', 'twl_index', 'twl_partitions'
    )

    essential: 'Optional[ExeFSReader]'

    ctr_partitions: 'List[Tuple[int, int]]'
    twl_partitions: 'List[Tuple[int, int]]'

    def __init__(self, file: 'FilePathOrObject', mode: str = 'rb', *, closefd: bool = True, crypto: CryptoEngine = None,
                 dev: bool = False, otp: bytes = None, otp_file: 'FilePath' = None, cid: bytes = None,
                 cid_file: 'FilePath' = None, auto_raise_exceptions: bool = True):
        super().__init__(file=file, mode=mode, closefd=closefd, crypto=crypto, dev=dev)

        self._lock = Lock()

        # set up otp if it was provided
        # otherwise it has to be in essential.exefs or set up manually with a custom CryptoEngine object
        if otp:
            logger.info('Using OTP from function arguments')
            self._crypto.setup_keys_from_otp(otp)
        elif otp_file:
            logger.info('Using OTP from file %s', otp_file)
            self._crypto.setup_keys_from_otp_file(otp_file)

        # opened files to close if the NAND is closed
        # noinspection PyTypeChecker
        self._open_files: Set[SubsectionIO] = WeakSet()

        self._file.seek(0, 2)
        raw_nand_size = self._file.tell() - self._start
        self._subfile = SubsectionIO(self._file, self._start, raw_nand_size)

        header_raw = self._subfile.read(0x200)
        self.header = NANDNCSDHeader.from_bytes(header_raw)

        # check for essential.exefs
        self.essential = None
        try:
            essential = ExeFSReader(self._subfile, closefd=False)
        except InvalidExeFSError:
            pass
        else:
            # check if essential.exefs has anything at all (no files means there isn't actually an exefs here)
            if essential.entries:
                self.essential = essential
                logger.info('essential.exefs loaded from NAND')
            else:
                logger.info('essential.exefs not found')

        # While I could hardcode the indexes that are used on all retail units,
        # I would prefer that this is stable with modified nands
        # I wonder what happens if you try to do something like have two ctrnands though?
        # For the time being, this just tries to get the first one of each
        self.twl_index = None
        for idx, info in self.header.partition_table.items():
            if info.base_file == 'twl':
                self.twl_index = idx
                logger.info('Found TWL partition at index %i', idx)
                break
        else:
            logger.warning('Could not find the TWL partition, twl_index will be None '
                           'and TWL partitions will be unavailable')

        self.ctr_index = None
        for idx, info in self.header.partition_table.items():
            if info.base_file.startswith('ctr'):
                self.ctr_index = idx
                logger.info('Found CTR partition at index %i', idx)
                break
        else:
            logger.warning('Could not find the CTR partition, ctr_index will be None '
                           'and CTR partitions will be unavailable')

        if not self._crypto.otp_keys_set:
            if self.essential:
                try:
                    with self.essential.open('otp') as f:
                        otp = f.read(0x100)
                    self._crypto.setup_keys_from_otp(otp)
                except ExeFSFileNotFoundError:
                    raise MissingOTPError('OTP was not provided in the otp or otp_file arguments, '
                                          'and otp is not in essential.exefs')
            else:
                raise MissingOTPError('OTP was not provided in the otp or otp_file arguments, '
                                      'and essential.exefs is missing')

        # cid should take precedence over the file
        if cid_file and not cid:
            with open(cid_file, 'rb') as f:
                cid = f.read(0x10)
                logger.info('Loaded CID from file %s', cid_file)

        # if cid is still not provided, try to get it from essential.exefs
        if not cid:
            if self.essential:
                try:
                    with self.essential.open('nand_cid') as f:
                        cid = f.read(0x10)
                        logger.info('Loaded CID from embedded essential.exefs')
                except ExeFSFileNotFoundError:
                    pass  # an attempt to generate the counter from known data later

        self.counter = None
        self.counter_twl = None
        # generate the counter from the cid if it's available now
        if cid:
            self.counter = readbe(sha256(cid).digest()[0:0x10])
            self.counter_twl = readle(sha1(cid).digest()[0:0x10])
            logger.info('Counters for CTR and TWL generated from CID')
        else:
            logger.info('CID not provided. CTR index: %i; TWL index: %i', self.ctr_index, self.twl_index)
            # try to generate the counter from a known block of data that should not change normally
            if self.ctr_index is not None:
                self._generate_ctr_counter()
            if self.twl_index is not None:
                self._generate_twl_counter()

        # these do the actual de/encryption part and are used as the basis for SubsectionIO files
        self._base_files = {}

        self.ctr_partitions = []
        self.twl_partitions = []

        if self.counter:
            self._base_files.update({
                'ctr_old': self._crypto.create_ctr_io(Keyslot.CTRNANDOld, self._subfile, self.counter),
                'ctr_new': self._crypto.create_ctr_io(Keyslot.CTRNANDNew, self._subfile, self.counter),
                'firm': self._crypto.create_ctr_io(Keyslot.FIRM, self._subfile, self.counter),
                'agb': self._crypto.create_ctr_io(Keyslot.AGB, self._subfile, self.counter),
            })

            with self.open_ncsd_partition(self.ctr_index) as f:
                f.seek(0x1BE)
                ctr_mbr = f.read(0x42)
                try:
                    self.ctr_partitions = parse_mbr_lazy(ctr_mbr)
                    logger.info('Loaded CTR partitions')
                except InvalidNANDError:
                    logger.error('Could not load CTR partitions', exc_info=True)

        if self.counter_twl:
            self._base_files['twl'] = self._crypto.create_ctr_io(Keyslot.TWLNAND, self._subfile, self.counter_twl)

            with self.open_ncsd_partition(self.twl_index) as f:
                f.seek(0x1BE)
                twl_mbr = f.read(0x42)
                try:
                    self.twl_partitions = parse_mbr_lazy(twl_mbr)
                    logger.info('Loaded TWL partitions')
                except InvalidNANDError:
                    # corrupted mbr, which can happen in the case of the NCSD header being from the wrong console
                    # this is (or was) a somewhat common case, so we will copy the default mbr here
                    logger.error('Could not load TWL partitions, using default information', exc_info=True)
                    self.twl_partitions = DEFAULT_TWL_MBR_INFO.copy()

        if auto_raise_exceptions:
            self.raise_if_ctr_failed()
            self.raise_if_twl_failed()

        # check for GodMode9 bonus drive
        #self._file.seek()

    def _generate_ctr_counter(self):
        """
        Attempt to generate the Counter for the CTR parts of the NAND. This will only be used if a NAND CID is not
        provided or found in essential.exefs.

        This will try to use a known block that is identical for all consoles. This will fail if the CTR MBR is
        modified.
        """

        part_info = self.header.partition_table[self.ctr_index]
        if part_info.encryption_type == PartitionEncryptionType.CTR:
            keyslot = Keyslot.CTRNANDOld
        elif part_info.encryption_type == PartitionEncryptionType.New3DSCTR:
            keyslot = Keyslot.CTRNANDNew
        else:
            raise InvalidNANDError(f'Unknown encryption type {part_info.encryption_type} when attempting to generate '
                                   f'CTR Counter')

        logger.info('Attempting to generate CTR Counter using keyslot: %s', keyslot)

        # Seek to a part of the CTR MBR that should be all zeros when decrypted
        self._subfile.seek(part_info.offset + 0x1D0)
        block_offset = self._subfile.tell() >> 4

        # These two blocks should be all zeros, therefore nothing to XOR.
        # The first one is decrypted using ECB then subtracted with block_offset to hopefully generate the counter.
        # The second one is used to test the decryption. If it succeeds, then the counter was found.
        ctrn_block_0x1d = self._subfile.read(0x10)
        ctrn_block_0x1e = self._subfile.read(0x10)

        # Attempt to decrypt the block
        ctr_counter_offs = self._crypto.create_ecb_cipher(keyslot).decrypt(ctrn_block_0x1d)
        # Subtract the block offset from the result. This results in the counter, maybe.
        ctr_counter = int.from_bytes(ctr_counter_offs, 'big') - block_offset

        # Decrypt the next block using the counter
        out = self._crypto.create_ctr_cipher(keyslot, ctr_counter + block_offset + 1).decrypt(ctrn_block_0x1e)
        if out == EMPTY_BLOCK:
            # Counter is verified, so it can be used
            self.counter = ctr_counter
            logger.info('CTR Counter generated')
        else:
            logger.warning('Failed to generate CTR Counter')

    def _generate_twl_counter(self):
        """
        Attempt to generate the Counter for the TWL parts of the NAND. This will only be used if a NAND CID is not
        provided or found in essential.exefs.

        This will try to use a known block that is identical for all consoles. This will fail if the TWL MBR is
        corrupt or modified.
        """

        part_info = self.header.partition_table[self.twl_index]

        logger.info('Attempting to generate TWL Counter')

        # Seek to a part of the TWL MBR that we know the data of
        self._subfile.seek(part_info.offset + 0x1C0)
        block_offset = self._subfile.tell() >> 4

        # The data of these two blocks should be the same on most consoles.
        # The first one is decrypted using ECB, then xored with the known data.
        # Then it's subtracted with the block offset.
        # The second one is used to test the decryption. If it succeeds, then the counter was found.
        twln_block_0x1c = self._subfile.read(0x10)
        twln_block_0x1d = self._subfile.read(0x10)

        # This is basically a known plaintext attack, except we have the keys. We just need the counter.
        # Normally the counter is encrypted, then xored with the plaintext to create the ciphertext.
        # If we xor the ciphertext with the known plaintext, we get the encrypted counter.
        # Decrypt that and subtract the block offset, and you get the counter (hopefully).
        twl_block_xored = int.from_bytes(twln_block_0x1c, 'big') ^ 0x18000601A03F97000000A97D04000004
        twl_counter_offs = self._crypto.create_ecb_cipher(Keyslot.TWLNAND).decrypt(
            twl_block_xored.to_bytes(0x10, 'little'))
        twl_counter = int.from_bytes(twl_counter_offs, 'big') - block_offset

        # Decrypt the next block using the counter
        out = self._crypto.create_ctr_cipher(Keyslot.TWLNAND, twl_counter + block_offset + 1).decrypt(twln_block_0x1d)
        if out == b'\x8e@\x06\x01\xa0\xc3\x8d\x80\x04\x00\xb3\x05\x01\x00\x00\x00':
            # Counter is verified, so it can be used
            self.counter_twl = twl_counter
            logger.info('TWL Counter generated')
        else:
            logger.warning('Failed to generate TWL Counter')

    def close(self):
        if not self.closed:
            for c in self._base_files.values():
                c.close()
            for s in self._open_files:
                s.close()

            if self.essential:
                self.essential.close()

            self._open_files = set()
            self._base_files = {}

            super().close()

    def raise_if_ctr_failed(self):
        """
        Raise an error if CTR partitions are inaccessible.

        :raises InvalidNANDError:
        """

        if not self.ctr_partitions:
            raise InvalidNANDError('CTR partitions are inaccessible')

    def raise_if_twl_failed(self):
        """
        Raise an error if TWL partitions are inaccessible.

        :raises InvalidNANDError:
        """

        if not self.twl_partitions:
            raise InvalidNANDError('TWL partitions are inaccessible')

    def open_ctr_partition(self, partition_index: int = 0):
        """
        Opens a raw partition in CTRNAND for reading and writing.

        In practice there is only ever one, so this opens it by default.

        :param partition_index: Partition index number.
        :return: A file-like object.
        :rtype: SubsectionIO
        """

        # To make things simpler to deal with, this creates a SubsectionIO object directly on the base file
        #     instead of opening it with open_ncsd_partition first
        # Why is this simpler? It means I don't have to deal with stacking SubsectionIO objects and dealing with
        #     closing them when they're done.
        # It's also probably a tiny bit faster, probably.
        ctr_ncsd_info = self.header.partition_table[self.ctr_index]
        ctr_mbr_info = self.ctr_partitions[partition_index]
        fh = SubsectionIO(self._base_files[ctr_ncsd_info.base_file],
                          ctr_ncsd_info.offset + ctr_mbr_info[0],
                          ctr_mbr_info[1])
        self._open_files.add(fh)
        return fh

    def open_twl_partition(self, partition_index: int):
        """
        Opens a raw partition in TWLNAND for reading and writing.

        0 is TWL NAND and 1 is TWL Photo.

        :param partition_index: Partition index number.
        :return: A file-like object.
        :rtype: SubsectionIO
        """
        twl_ncsd_info = self.header.partition_table[self.twl_index]
        twl_mbr_info = self.twl_partitions[partition_index]
        fh = SubsectionIO(self._base_files[twl_ncsd_info.base_file],
                          twl_ncsd_info.offset + twl_mbr_info[0],
                          twl_mbr_info[1])
        self._open_files.add(fh)
        return fh

    def open_ncsd_partition(self, partition_index: int):
        """
        Opens a raw NCSD partition for reading and writing.

        Note: If you are looking to read from TWLNAND or CTRNAND, you may be looking for :meth:`open_twl_partition`
        or :meth:`open_ctr_partition` instead.

        :param partition_index: Partition index number.
        :return: A file-like object.
        :rtype: SubsectionIO
        """
        info = self.header.partition_table[partition_index]
        fh = SubsectionIO(self._base_files[info.base_file], info.offset, info.size)
        self._open_files.add(fh)
        return fh
