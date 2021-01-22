# This file is a part of pyctr.
#
# Copyright (c) 2017-2021 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

"""Module for interacting with NCCH files."""

from hashlib import sha256
from enum import IntEnum
from math import ceil
from os import PathLike
from threading import Lock
from typing import TYPE_CHECKING, NamedTuple

from ..common import PyCTRError, _ReaderOpenFileBase
from ..crypto import CryptoEngine, Keyslot, add_seed, get_seed
from ..fileio import SubsectionIO
from ..util import readle, roundup
from .base import TypeReaderCryptoBase
from .exefs import ExeFSReader, EXEFS_HEADER_SIZE
from .romfs import RomFSReader

if TYPE_CHECKING:
    from typing import BinaryIO, Dict, List, Optional, Tuple, Union

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
    # determines the extra keyslot used for RomFS and parts of ExeFS
    crypto_method: int
    # if this is a CXI (CTR Executable Image) or CFA (CTR File Archive)
    # in the raw flags, "Data" has to be set for it to be a CFA, while "Executable" is unset.
    executable: bool
    # if the content is encrypted using a fixed normal key.
    fixed_crypto_key: bool
    # if RomFS is to be ignored
    no_romfs: bool
    # if the NCCH has no encryption
    no_crypto: bool
    # if a seed must be loaded to load RomFS and parts of ExeFS
    uses_seed: bool


class _NCCHSectionFile(_ReaderOpenFileBase):
    """
    Provides a raw, decrypted NCCH section as a file-like object.

    This is only used in two cases:

    - An ExeFS when an extra keyslot is used. Parts of the ExeFS are decrypted using Original NCCH (the header, icon,
      and banner), while the rest uses the extra keyslot. This is done to retain compatibility with Nintendo 3DS
      systems that don't support the extra keyslot. The .code would never be loaded on these old systems, since an
      update prompt on the HOME Menu would prevent the title from starting.
    - The simulated fully-decrypted NCCH. Since this loads from multiple sections with varying encryption, complex
      handling is required. This is done in `get_data` of :class:`NCCHReader`.

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
    :param crypto: A custom :class:`crypto.CryptoEngine` object to be used. Defaults to None, which causes a new one to
        be created.
    :param dev: Use devunit keys.
    :param seed: Seed to use. This is a quick way to add a seed using :func:`~.seeddb.add_seed`.
    :param load_sections: Load the ExeFS and RomFS as :class:`type.exefs.ExeFSReader` and
        :class:`type.romfs.RomFSReader` objects.
    :param assume_decrypted: Assume each NCCH content is decrypted. Needed if the image was decrypted without fixing
        the NCCH flags.
    """

    # this is the KeyY when generated using the seed
    _seeded_key_y = None

    closed = False
    """`True` if the reader is closed."""

    sections: 'Dict[NCCHSection, NCCHRegion]'
    """Contains all the sections the NCCH has."""

    # this lists the ranges of the ExeFS to decrypt with Original NCCH (see load_sections)
    _exefs_keyslot_normal_range: 'List[Tuple[int, int]]'

    exefs: 'Optional[ExeFSReader]' = None
    """The :class:`~.ExeFSReader` of the NCCH, if it has one."""

    romfs: 'Optional[RomFSReader]' = None
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

    def __init__(self, file: 'Union[PathLike, str, bytes, BinaryIO]', *, closefd: bool = None,
                 case_insensitive: bool = True, crypto: CryptoEngine = None, dev: bool = False, seed: bytes = None,
                 load_sections: bool = True, assume_decrypted: bool = False):

        super().__init__(file, closefd=closefd, crypto=crypto, dev=dev)

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
        # load the seed verify field, which is part of an sha256 hash to verify if
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
        flags_raw = header[0x188:0x190]
        self.flags = NCCHFlags(crypto_method=flags_raw[3], executable=bool(flags_raw[5] & 0x2),
                               fixed_crypto_key=bool(flags_raw[7] & 0x1), no_romfs=bool(flags_raw[7] & 0x2),
                               no_crypto=bool(flags_raw[7] & 0x4), uses_seed=bool(flags_raw[7] & 0x20))

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

        # load the (seeded, if needed) key into the extra keyslot
        self._crypto.set_keyslot('y', self.extra_keyslot, self.get_key_y())

        # load the sections using their specific readers
        if load_sections:
            self.load_sections()

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
            # this is to generate what regions should be decrypted with the Original NCCH keyslot
            # technically, it's not actually 0x200 chunks or units. the actual space of the file
            #   is encrypted with the different key. for example, if .code is 0x300 bytes, that
            #   means the first 0x300 are encrypted with the NCCH 7.x key, and the remaining
            #   0x100 uses Original NCCH. however this would be quite a pain to implement properly
            #   with random access, so I only work with 0x200 chunks here. after all, the space
            #   after the file is effectively unused. it makes no difference, except for
            #   perfectionists who want it perfectly decrypted. GodMode9 does it properly I think,
            #   if that is what you want. or you can fix the empty space yourself with a hex editor.
            self._exefs_keyslot_normal_range = [(0, 0x200)]
            exefs_fp = self.open_raw_section(NCCHSection.ExeFS)
            # load the ExeFS reader
            # icon is not loaded since we need to figure out its section offset and size first
            self.exefs = ExeFSReader(exefs_fp, _load_icon=False)

            for entry in self.exefs.entries.values():
                if entry.name in EXEFS_NORMAL_CRYPTO_FILES:
                    # this will add the offset (relative to ExeFS start), with the size
                    #   rounded up to 0x200 chunks
                    r = (entry.offset + EXEFS_HEADER_SIZE,
                         entry.offset + EXEFS_HEADER_SIZE + roundup(entry.size, NCCH_MEDIA_UNIT))
                    self._exefs_keyslot_normal_range.append(r)

            self.exefs._load_icon()

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
        # check if the region is ExeFS and uses a newer keyslot, or is fulldec, and use a specific file class
        if (section == NCCHSection.ExeFS and self.extra_keyslot) or (section == NCCHSection.FullDecrypted):
            return _NCCHSectionFile(self, section)
        else:
            region = self.sections[section]
            fh = SubsectionIO(self._file, self._start + region.offset, region.size)
        # if the region is encrypted (not ExeFS if an extra keyslot is in use), wrap it in CTRFileIO
        if not (self._assume_decrypted or self.flags.no_crypto or section in NO_ENCRYPTION):
            keyslot = self.extra_keyslot if region.section == NCCHSection.RomFS else self.main_keyslot
            fh = self._crypto.create_ctr_io(keyslot, fh, region.iv)
        return fh

    def get_key_y(self, original: bool = False) -> bytes:
        if original or not self.flags.uses_seed:
            return self._key_y
        if self.flags.uses_seed and not self._seed_set_up:
            raise MissingSeedError('NCCH uses seed crypto, but seed is not set up')
        else:
            return self._seeded_key_y

    def check_for_extheader(self) -> bool:
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
            if region.section == NCCHSection.ExeFS and self.flags.crypto_method != 0x00:
                # get the amount to cut off at the beginning
                before = offset % 0x200

                # get the offset of the starting chunk
                aligned_offset = offset - before

                # get the real offset of the starting chunk
                aligned_real_offset = self._start + region.offset + aligned_offset

                # get the aligned total size of the requested size
                aligned_size = size + before
                self._file.seek(aligned_real_offset)

                def do_thing(al_offset: int, al_size: int, cut_start: int, cut_end: int):
                    # get the offset of the end of the last chunk
                    end = al_offset + (ceil(al_size / 0x200) * 0x200)

                    # get the offset to the last chunk
                    last_chunk_offset = end - 0x200

                    # noinspection PyTypeChecker
                    for chunk in range(al_offset, end, 0x200):
                        # generate the IV for this chunk
                        iv = region.iv + (chunk >> 4)

                        # get the extra keyslot
                        keyslot = self.extra_keyslot

                        for r in self._exefs_keyslot_normal_range:
                            if r[0] <= self._file.tell() - region.offset < r[1]:
                                # if the chunk is within the "normal keyslot" ranges,
                                #   use the Original NCCH keyslot instead
                                keyslot = self.main_keyslot

                        # decrypt the data
                        out = self._crypto.create_ctr_cipher(keyslot, iv).decrypt(self._file.read(0x200))
                        if chunk == al_offset:
                            # cut off the beginning if it's the first chunk
                            out = out[cut_start:]
                        if chunk == last_chunk_offset and cut_end != 0x200:
                            # cut off the end of it's the last chunk
                            out = out[:-cut_end]
                        yield out

                # join all the chunks into one bytes result and return it
                return b''.join(do_thing(aligned_offset, aligned_size, before, 0x200 - ((size + before) % 0x200)))
            else:
                # this is currently used to support FullDecrypted. other sections use SubsectionIO + CTRFileIO.

                # seek to the real offset of the section + the requested offset
                self._file.seek(self._start + region.offset + offset)
                data = self._file.read(size)

                # choose the extra keyslot only for RomFS here
                # ExeFS needs special handling if a newer keyslot is used, therefore it's not checked here
                keyslot = self.extra_keyslot if region.section == NCCHSection.RomFS else self.main_keyslot

                # get the amount of padding required at the beginning
                before = offset % 16

                # pad the beginning of the data if needed (the ending part doesn't need padding)
                data = (b'\0' * before) + data

                # decrypt the data, then cut off the padding
                return self._crypto.create_ctr_cipher(keyslot, region.iv + (offset >> 4)).decrypt(data)[before:]
