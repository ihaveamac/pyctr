# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

"""Module for interacting with NCCH files."""

from hashlib import sha256
from enum import IntEnum
from math import ceil
from threading import Lock
from typing import TYPE_CHECKING, NamedTuple

from ..common import PyCTRError, _ReaderOpenFileBase
from ..crypto import CryptoEngine, Keyslot, add_seed, get_seed
from ..fileio import SplitFileMerger, SubsectionIO
from ..util import readle
from .base import TypeReaderCryptoBase
from .exefs import ExeFSReader
from .romfs import RomFSReader

if TYPE_CHECKING:
    from typing import BinaryIO, Dict, List, Optional, Tuple, Union
    from ..common import FilePathOrObject

__all__ = ['NCCH_MEDIA_UNIT', 'NO_ENCRYPTION', 'EXEFS_NORMAL_CRYPTO_FILES', 'FIXED_SYSTEM_KEY', 'NCCHError',
           'InvalidNCCHError', 'NCCHSeedError', 'MissingSeedError', 'extra_cryptoflags', 'NCCHSection', 'NCCHRegion',
           'NCCHFlags', 'NCCHReader']


class NCCHError(PyCTRError):
    """Generic exception for NCCH operations."""


class InvalidNCCHError(NCCHError):
    """Invalid NCCH header exception."""


class NCCHSeedError(NCCHError):
    """NCCH seed is not set up, or attempted to set up seed when seed crypto is not used."""


class MissingSeedError(NCCHSeedError):
    """Seed could not be found."""


# NCCH sections are stored in media units
# for example, ExeFS may be stored in 13 media units, which is 0x1A00 bytes (13 * 0x200)
NCCH_MEDIA_UNIT = 0x200
# depending on the crypto_method flag, a different keyslot may be used for RomFS and parts of ExeFS.
extra_cryptoflags = {0x00: Keyslot.NCCH, 0x01: Keyslot.NCCH70, 0x0A: Keyslot.NCCH93, 0x0B: Keyslot.NCCH96}

# if fixed_crypto_key is enabled, the normal key is normally all zeros.
# however is (program_id & (0x10 << 32)) is true, this key is used instead.
FIXED_SYSTEM_KEY = 0x527CE630A9CA305F3696F3CDE954194B


# this is IntEnum to make generating the IV easier
class NCCHSection(IntEnum):
    ExtendedHeader = 1
    ExeFS = 2
    RomFS = 3

    # no crypto
    Header = 4
    Logo = 5
    Plain = 6

    # special
    FullDecrypted = 7
    Raw = 8


# these sections don't use encryption at all
NO_ENCRYPTION = {NCCHSection.Header, NCCHSection.Logo, NCCHSection.Plain, NCCHSection.Raw}
# the contents of these files in the ExeFS, plus the header, will always use the Original NCCH keyslot
# therefore these regions need to be stored to check what keyslot is used to decrypt
EXEFS_NORMAL_CRYPTO_FILES = {'icon', 'banner'}


class NCCHRegion(NamedTuple):
    section: 'NCCHSection'
    offset: int
    size: int
    end: int  # this is just offset + size, stored to avoid re-calculation later on
    # not all sections will actually use this (see NCCHSection), so some have a useless value
    iv: int


class NCCHFlags(NamedTuple):
    """Flags for an NCCH. This is not a complete set. See: https://3dbrew.org/wiki/NCCH#NCCH_Flags"""

    crypto_method: int
    """
    Determines the extra keyslot used for RomFS and parts of ExeFS. 0x00 = NCCH, 0x01 = NCCH70, 0x0A = NCCH93,
    0x0B = NCCH96
    """

    executable: bool
    """
    If this content is a CXI (CTR Executable Image) or CFA (CTR File Archive). In the raw flags, "Data" needs
    to be set with "Executable" unset for this to be a CFA.
    """

    fixed_crypto_key: bool
    """
    If a fixed normal key is used to encrypt the contents. This is often a zero-key, with a different
    "fixed system key" used in specfic situations.
    """

    no_romfs: bool
    """Determines if there is no RomFS."""

    no_crypto: bool
    """If no encryption is used at all. This takes precedence over other encryption flags."""

    uses_seed: bool
    """If a seed is used in conjunction with the extra keyslot."""

    @classmethod
    def from_bytes(cls, flag_bytes: bytes) -> 'NCCHFlags':
        return cls(crypto_method=flag_bytes[3], executable=bool(flag_bytes[5] & 0x2),
                   fixed_crypto_key=bool(flag_bytes[7] & 0x1), no_romfs=bool(flag_bytes[7] & 0x2),
                   no_crypto=bool(flag_bytes[7] & 0x4), uses_seed=bool(flag_bytes[7] & 0x20))


# noinspection PyAbstractClass
class _NCCHSectionFile(_ReaderOpenFileBase):
    """
    Provides a raw, decrypted NCCH section as a file-like object.

    This is used for the simulated fully-decrypted NCCH. Since this loads from multiple sections with varying
    encryption, complex handling is required. This is done in `get_data` of :class:`NCCHReader`.

    In all other cases a :class:`crypto.CTRFileIO` object is used for encrypted sections, or
    :class:`fileio.SubsectionIO` for decrypted.
    """

    def __init__(self, reader: 'NCCHReader', path: 'NCCHSection'):
        super().__init__(reader, path)
        self._info = reader.sections[path]


class NCCHReader(TypeReaderCryptoBase):
    """
    Reads the contents of NCCH containers.

    The NCCH header contains information such as Title ID, Product Code, flags, and section info.

    NCCH containers can be classified as a CTR Executable Image (CXI) if it has executable code, or a CTR File Archive
    (CFA) if it doesn't.

    A CXI can contain:

    - an Extended Header (extheader) with executable info and access permissions
    - a logo region (for titles released before System Menu 5.0.0-11, this is in the ExeFS)
    - a plain region with SDK library strings
    - an Executable Filesystem (ExeFS) with .code, icon, and banner
    - a Read-only Filesystem (RomFS)

    A CFA can contain:

    - an ExeFS with icon and banner
    - a RomFS

    :param file: A file path or a file-like object with the NCCH data.
    :param case_insensitive: Use case-insensitive paths for the RomFS.
    :param crypto: A custom :class:`~.CryptoEngine` object to be used. Defaults to None, which causes a new one to
        be created.
    :param dev: Use devunit keys.
    :param seed: Seed to use. This is a quick way to add a seed using :func:`~.seeddb.add_seed`.
    :param load_sections: Load the ExeFS and RomFS as :class:`~.ExeFSReader` and
        :class:`~.RomFSReader` objects.
    :param assume_decrypted: Assume each NCCH content is decrypted. Needed if the image was decrypted without fixing
        the NCCH flags.
    """

    __slots__ = (
        '_all_sections', '_assume_decrypted', '_case_insensitive', '_exefs_crypto_ranges', '_exefs_fp',
        '_exefs_special_handling', '_key_y', '_lock', '_seed_set_up', '_seed_verify', '_seeded_key_y', 'closed',
        'content_size', 'exefs', 'extra_keyslot', 'flags', 'main_keyslot', 'partition_id', 'product_code', 'program_id',
        'romfs', 'sections', 'version'
    )

    # this is the KeyY when generated using the seed
    _seeded_key_y: 'Optional[bytes]'

    sections: 'Dict[NCCHSection, NCCHRegion]'
    """Contains all the sections the NCCH has."""

    # this is used in the NCCH's ExeFSReader and in FullDecrypted
    # because it can have special encryption handling, this is set up beforehand
    _exefs_fp: 'BinaryIO'

    # this lists the ranges of the exefs (start + end) and the keyslot to use
    # the keyslot should alternate between main and extra for each entry, staring with main (for header)
    _exefs_crypto_ranges: 'List[Tuple[int, int, int]]'

    exefs: 'Optional[ExeFSReader]'
    """The :class:`~.ExeFSReader` of the NCCH, if it has one."""

    romfs: 'Optional[RomFSReader]'
    """The :class:`~.RomFSReader` of the NCCH, if it has one."""

    program_id: str
    """Title ID of the application."""

    partition_id: str
    """
    Partition ID as an integer. Usually this is different for NCCH in a title, incrementing the platform section
    (e.g. 0004 for Application, 0005 for Manual, 0006 for Download Play Child). DLC does not follow this, all contents
    use 0004 for the platform.
    """

    product_code: str
    """Product code of the content."""

    content_size: int
    """Expected size of the NCCH container in bytes."""

    flags: NCCHFlags
    """NCCH flags of the container."""

    version: int
    """NCCH version. Not to be confused with the title version."""

    main_keyslot: Keyslot
    """
    Keyslot to use for decrypting the Extended Header and ExeFS header. In most cases this is Original NCCH (0x2C).
    Some titles may use a fixed crypto key though, either all zeros, or a special key for system titles. PyCTR uses the
    fake keyslots 0x41 and 0x42 for these respectively.
    """

    extra_keyslot: Keyslot
    """
    Second keyslot to use for the ExeFS contents and RomFS. This is determined by the crypto method in the NCCH flags.
    This is set to the same as main_keyslot for titles without an extra crypto method, or with a fixed crypto key.
    """

    def __init__(self, file: 'FilePathOrObject', *, closefd: bool = None,
                 case_insensitive: bool = True, crypto: CryptoEngine = None, dev: bool = False, seed: bytes = None,
                 load_sections: bool = True, assume_decrypted: bool = False):

        super().__init__(file, closefd=closefd, crypto=crypto, dev=dev)

        self.closed = False
        self.exefs = None
        self.romfs = None

        # Threading lock to prevent two operations on one class instance from interfering with eachother.
        self._lock = Lock()

        # old decryption methods did not fix the flags, so sometimes we have to assume it is decrypted
        self._assume_decrypted = assume_decrypted

        # store case-insensitivity for RomFSReader
        self._case_insensitive = case_insensitive

        header = self._file.read(0x200)

        # load the Key Y from the first 0x10 of the signature
        self._key_y = header[0x0:0x10]
        # store the ncch version
        self.version = readle(header[0x112:0x114])
        # get the total size of the NCCH container, and store it in bytes
        self.content_size = readle(header[0x104:0x108]) * NCCH_MEDIA_UNIT
        # get the Partition ID, which is used in the encryption
        # this is generally different for each content in a title, except for DLC
        # the int is used to generate the IV for each section
        partition_id_int = readle(header[0x108:0x110])
        self.partition_id = f'{partition_id_int:016x}'
        # load the seed verify field, which is part of a sha256 hash to verify if
        #   a seed is correct for this title
        self._seed_verify = header[0x114:0x118]
        # load the Product Code store it as a unicode string
        self.product_code = header[0x150:0x160].decode('ascii').strip('\0')
        # load the Program ID
        # this is the Title ID, and is usually the same for each section
        self.program_id = header[0x118:0x120][::-1].hex()
        # load the extheader size, but this code only uses it to determine if it exists
        extheader_size = readle(header[0x180:0x184])

        # each section is stored with the section ID, then the region information (offset, size, IV)
        self.sections = {}
        # same as above, but includes non-existent regions too, for the full-decrypted handler
        self._all_sections = {}

        def add_region(section: 'NCCHSection', starting_unit: int, units: int):
            offset = starting_unit * NCCH_MEDIA_UNIT
            size = units * NCCH_MEDIA_UNIT
            region = NCCHRegion(section=section,
                                offset=offset,
                                size=size,
                                end=offset + size,
                                iv=partition_id_int << 64 | (section << 56))
            self._all_sections[section] = region
            if units != 0:  # only add existing regions
                self.sections[section] = region

        # add the header as the first region
        add_region(NCCHSection.Header, 0, 1)

        # add the full decrypted content, which when read, simulates a fully decrypted NCCH container
        add_region(NCCHSection.FullDecrypted, 0, self.content_size // NCCH_MEDIA_UNIT)
        # add the full raw content
        add_region(NCCHSection.Raw, 0, self.content_size // NCCH_MEDIA_UNIT)

        # only care about the exheader if it's the expected size
        if extheader_size == 0x400:
            add_region(NCCHSection.ExtendedHeader, 1, 4)
        else:
            add_region(NCCHSection.ExtendedHeader, 0, 0)

        # add the remaining NCCH regions
        # some of these may not exist, and won't be added if units (second value) is 0
        add_region(NCCHSection.Logo, readle(header[0x198:0x19C]), readle(header[0x19C:0x1A0]))
        add_region(NCCHSection.Plain, readle(header[0x190:0x194]), readle(header[0x194:0x198]))
        add_region(NCCHSection.ExeFS, readle(header[0x1A0:0x1A4]), readle(header[0x1A4:0x1A8]))
        add_region(NCCHSection.RomFS, readle(header[0x1B0:0x1B4]), readle(header[0x1B4:0x1B8]))

        # parse flags
        self.flags = NCCHFlags.from_bytes(header[0x188:0x190])

        if self.flags.fixed_crypto_key:
            self.main_keyslot = Keyslot.FixedSystemKey if int(self.program_id, 16) & (0x10 << 32) else Keyslot.ZeroKey
            self.extra_keyslot = self.main_keyslot
        else:
            self.main_keyslot = Keyslot.NCCH
            self.extra_keyslot = extra_cryptoflags[self.flags.crypto_method]

        # load the original (non-seeded) KeyY into the Original NCCH slot
        self._crypto.set_keyslot('y', Keyslot.NCCH, self.get_key_y(original=True))

        # tells if the right seed has been set up
        self._seed_set_up = False

        if seed:
            add_seed(self.program_id, seed)

        # load the seed if needed
        if self.flags.uses_seed:
            self.setup_seed(get_seed(self.program_id))

        # this would fail if zero-key and a seed is used, but I have *no* idea how that would work
        # (if it's even possible)
        if self.flags.fixed_crypto_key:
            self._crypto.set_normal_key(Keyslot.NCCHExtraKey, self._crypto.key_normal[self.extra_keyslot])
        else:
            # load the (seeded, if needed) key into the extra keyslot
            self._crypto.set_keyslot('x', Keyslot.NCCHExtraKey, self._crypto.key_x[self.extra_keyslot])
            self._crypto.set_keyslot('y', Keyslot.NCCHExtraKey, self.get_key_y())

        # checks in case ExeFS is encrypted with the extra keyslot (otherwise, decrypt normally)
        self._exefs_special_handling = False
        if not self.flags.no_crypto:
            if self.main_keyslot != self.extra_keyslot:
                self._exefs_special_handling = True
            elif self.flags.uses_seed:
                # a few titles use the same keyslot for main + extra, but also use seed
                self._exefs_special_handling = True

        # load the sections using their specific readers
        if load_sections:
            self.load_sections()

    def close(self):
        super().close()
        try:
            self._exefs_fp.close()
        except AttributeError:
            pass

    def __repr__(self):
        info = [('program_id', self.program_id), ('product_code', self.product_code)]
        try:
            info.append(('title_name', repr(self.exefs.icon.get_app_title().short_desc)))
        except (KeyError, AttributeError):
            info.append(('title_name', 'unknown'))
        info_final = " ".join(x + ": " + str(y) for x, y in info)
        return f'<{type(self).__name__} {info_final}>'

    def load_sections(self):
        """Load the sections of the NCCH (Extended Header, ExeFS, and RomFS)."""

        # try to load the ExeFS
        try:
            self._file.seek(self._start + self.sections[NCCHSection.ExeFS].offset)
        except KeyError:
            pass  # no ExeFS
        else:
            if self._exefs_special_handling:
                # Get the sections that are encrypted with the extra keyslot. This includes any part that is not the
                # header, "icon", "banner". This is how the 3DS treats it; any other file is encrypted with the extra
                # keyslot. In practice this is only ".code", however if another file is forced in like "logo", it is
                # encrypted with the extra keyslot. So because this has a chance of happening, no matter how unlikely,
                # I have to do this properly. Assumptions with Nintendo formats have bitten me in the ass before.

                # Load the ExeFS to get the file offsets and sizes. It's re-created after once a new merged file is made
                # with the decrypted sections.
                exefs_tmp_fp = self._open_section_generic(NCCHSection.ExeFS)
                exefs_tmp = ExeFSReader(exefs_tmp_fp, closefd=False, _load_icon=False)

                # Starting from 0 and the original keyslot, this is every place where the crypto changes.
                # Example, 0 from 0x200 is original, then 0x200 to 0x380 is extra, then 0x380 to 0x400 is original,
                # then 0x400 to 0x700 is extra, then 0x700 to 0x800 is original, etc. The list in this case would look
                # like: [0x200, 0x380, 0x400, 0x700, 0x800]
                # This is a set to prevent duplicates. It turns into a sorted list after.
                crypto_changes_set = set()

                for name, info in exefs_tmp.entries.items():
                    if name not in {'icon', 'banner'}:
                        crypto_changes_set.add(info.offset + 0x200)
                        crypto_changes_set.add(info.offset + info.size + 0x200)
                crypto_changes_set.add(self.sections[NCCHSection.ExeFS].end)

                crypto_changes = sorted(crypto_changes_set)

                # This creates a list of start + end ranges, plus the keyslot used to decrypt them.
                # In open_raw_section it is used to create multiple SubsectionIO objects based on one of two CTRFileIO
                # objects, one for the main keyslot and one for extra. Then all of them are merged into one large
                # file with SplitFileMerger to provide easy access to the full decrypted ExeFS.
                self._exefs_crypto_ranges = []
                previous_offset = 0
                previous_keyslot = self.main_keyslot
                for offset in crypto_changes:
                    self._exefs_crypto_ranges.append((previous_offset, offset, previous_keyslot))
                    previous_offset = offset
                    previous_keyslot = self.main_keyslot if previous_keyslot is self.extra_keyslot else self.extra_keyslot

            # This will set up either the special ExeFS encryption from above, or a straightforward decryption
            # passthrough if not.
            self._exefs_fp = self.open_raw_section(NCCHSection.ExeFS)
            self.exefs = ExeFSReader(self._exefs_fp, closefd=False)

        # try to load RomFS
        if not self.flags.no_romfs:
            try:
                self._file.seek(self._start + self.sections[NCCHSection.RomFS].offset)
            except KeyError:
                pass  # no RomFS
            else:
                romfs_fp = self.open_raw_section(NCCHSection.RomFS)
                # load the RomFS reader
                self.romfs = RomFSReader(romfs_fp, case_insensitive=self._case_insensitive)

    def open_raw_section(self, section: 'NCCHSection'):
        """
        Open a raw NCCH section for reading with on-the-fly decryption.

        :param section: The section to open.
        :return: A file-like object that reads from the section.
        """
        if not self.flags.no_crypto:
            # check if the region is ExeFS and needs special handling, or is fulldec, and use a specific file class
            if section == NCCHSection.ExeFS and self._exefs_special_handling:
                region = self.sections[section]
                files = []
                main_io = self._open_section_generic(section, encryption=False)
                main_io = self._crypto.create_ctr_io(self.main_keyslot, main_io, region.iv)
                extra_io = self._open_section_generic(section, encryption=False)
                extra_io = self._crypto.create_ctr_io(Keyslot.NCCHExtraKey, extra_io, region.iv)
                for exefs_range in self._exefs_crypto_ranges:
                    base_file = main_io if exefs_range[2] is self.main_keyslot else extra_io
                    size = exefs_range[1] - exefs_range[0]
                    files.append((SubsectionIO(base_file, exefs_range[0], size), size))

                return SplitFileMerger(files, closefds=True)

            elif section == NCCHSection.FullDecrypted:
                return _NCCHSectionFile(self, section)
            else:
                return self._open_section_generic(section)
        return self._open_section_generic(section)

    def _open_section_generic(self, section: 'NCCHSection', encryption: bool = True):
        """
        Open a raw NCCH section but without special handling for ExeFS + FullDecrypted.
        This is used so the ExeFS header can be parsed to figure out how to decrypt it properly (see load_sections).

        :param section: The section to open.
        :param encryption: Whether or not to wrap it in a :class:`crypto.CTRFileIO` object, if necessary.
        :return: A file-like object that reads from the section.
        """
        region = self.sections[section]
        fh = SubsectionIO(self._file, self._start + region.offset, region.size)
        # if the region is encrypted (not ExeFS if an extra keyslot is in use), wrap it in CTRFileIO
        if encryption and not (self._assume_decrypted or self.flags.no_crypto or section in NO_ENCRYPTION):
            keyslot = Keyslot.NCCHExtraKey if region.section == NCCHSection.RomFS else self.main_keyslot
            fh = self._crypto.create_ctr_io(keyslot, fh, region.iv, closefd=True)
        self._open_files.add(fh)
        return fh

    def get_key_y(self, original: bool = False) -> bytes:
        if original or not self.flags.uses_seed:
            return self._key_y
        if self.flags.uses_seed and not self._seed_set_up:
            raise MissingSeedError('NCCH uses seed crypto, but seed is not set up')
        else:
            return self._seeded_key_y

    def check_for_extheader(self) -> bool:
        """
        Checks if the NCCH has an Extended Header.

        :return: True if it has an ExtHeader.
        :rtype: bool
        """
        return NCCHSection.ExtendedHeader in self.sections

    def setup_seed(self, seed: bytes):
        if not self.flags.uses_seed:
            raise NCCHSeedError('NCCH does not use seed crypto')
        seed_verify_hash = sha256(seed + bytes.fromhex(self.program_id)[::-1]).digest()
        if seed_verify_hash[0x0:0x4] != self._seed_verify:
            raise NCCHSeedError('given seed does not match with seed verify hash in header')
        self._seeded_key_y = sha256(self._key_y + seed).digest()[0:16]
        self._seed_set_up = True

    def get_data(self, section: 'Union[NCCHRegion, NCCHSection]', offset: int, size: int) -> bytes:
        """
        Get data from an NCCH section.

        :param section: A region or section to read from.
        :param offset: Offset from the section start.
        :param size: Data size.
        :return: Decrypted data from the region.
        """
        try:
            region = self._all_sections[section]
        except KeyError:
            region = section
        if offset + size > region.size:
            # prevent reading past the region
            size = region.size - offset

        # the full-decrypted handler is done outside of the thread lock
        if region.section == NCCHSection.FullDecrypted:
            before = offset % 0x200
            aligned_offset = offset - before
            aligned_size = size + before

            def do_thing(al_offset: int, al_size: int, cut_start: int, cut_end: int):
                # get the offset of the end of the last chunk
                end = al_offset + (ceil(al_size / 0x200) * 0x200)

                # store the sections to read
                # dict is ordered by default in CPython since 3.6.0, and part of the language spec since 3.7.0
                to_read: Dict[Tuple[NCCHSection, int], List[int]] = {}

                # get each section to a local variable for easier access
                header = self._all_sections[NCCHSection.Header]
                extheader = self._all_sections[NCCHSection.ExtendedHeader]
                logo = self._all_sections[NCCHSection.Logo]
                plain = self._all_sections[NCCHSection.Plain]
                exefs = self._all_sections[NCCHSection.ExeFS]
                romfs = self._all_sections[NCCHSection.RomFS]

                last_region = False

                # this is somewhat hardcoded for performance reasons. this may be optimized better later.
                for chunk_offset in range(al_offset, end, 0x200):
                    # RomFS check first, since it might be faster
                    if romfs.offset <= chunk_offset < romfs.end:
                        region = (NCCHSection.RomFS, 0)
                        curr_offset = romfs.offset

                    # ExeFS check second, since it might be faster
                    elif exefs.offset <= chunk_offset < exefs.end:
                        region = (NCCHSection.ExeFS, 0)
                        curr_offset = exefs.offset

                    elif header.offset <= chunk_offset < header.end:
                        region = (NCCHSection.Header, 0)
                        curr_offset = header.offset

                    elif extheader.offset <= chunk_offset < extheader.end:
                        region = (NCCHSection.ExtendedHeader, 0)
                        curr_offset = extheader.offset

                    elif logo.offset <= chunk_offset < logo.end:
                        region = (NCCHSection.Logo, 0)
                        curr_offset = logo.offset

                    elif plain.offset <= chunk_offset < plain.end:
                        region = (NCCHSection.Plain, 0)
                        curr_offset = plain.offset

                    else:
                        region = (NCCHSection.Raw, chunk_offset)
                        curr_offset = 0

                    if region not in to_read:
                        to_read[region] = [chunk_offset - curr_offset, 0]
                    to_read[region][1] += 0x200
                    last_region = region

                is_start = True
                for region, info in to_read.items():
                    new_data = self.get_data(region[0], info[0], info[1])
                    if region[0] == NCCHSection.Header:
                        # fix crypto flags
                        ncch_array = bytearray(new_data)
                        ncch_array[0x18B] = 0
                        ncch_array[0x18F] = 4
                        new_data = bytes(ncch_array)
                    if is_start:
                        new_data = new_data[cut_start:]
                        is_start = False
                    if region == last_region and cut_end != 0x200:
                        new_data = new_data[:-cut_end]

                    yield new_data

            return b''.join(do_thing(aligned_offset, aligned_size, before, 0x200 - ((size + before) % 0x200)))

        with self._lock:
            # check if decryption is really needed
            if self._assume_decrypted or self.flags.no_crypto or region.section in NO_ENCRYPTION:
                # this is currently used to support FullDecrypted. other sections use SubsectionIO + CTRFileIO.
                self._file.seek(self._start + region.offset + offset)
                return self._file.read(size)

            # thanks Stary2001 for help with random-access crypto

            # if the region is ExeFS and extra crypto is being used, special handling is required
            #   because different parts use different encryption methods
            if region.section == NCCHSection.ExeFS:
                self._exefs_fp.seek(offset)
                return self._exefs_fp.read(size)
            else:
                # this is currently used to support FullDecrypted. other sections use SubsectionIO + CTRFileIO.

                # seek to the real offset of the section + the requested offset
                self._file.seek(self._start + region.offset + offset)
                data = self._file.read(size)

                # choose the extra keyslot only for RomFS here
                # ExeFS needs special handling if a newer keyslot is used, therefore it's not checked here
                keyslot = Keyslot.NCCHExtraKey if region.section == NCCHSection.RomFS else self.main_keyslot

                # get the amount of padding required at the beginning
                before = offset % 16

                # pad the beginning of the data if needed (the ending part doesn't need padding)
                data = (b'\0' * before) + data

                # decrypt the data, then cut off the padding
                return self._crypto.create_ctr_cipher(keyslot, region.iv + (offset >> 4)).decrypt(data)[before:]
