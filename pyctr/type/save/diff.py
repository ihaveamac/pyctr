# This file is a part of pyctr.
#
# Copyright (c) 2017-2021 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from hashlib import sha256
from typing import TYPE_CHECKING

from ...util import readle
from .common import PartitionContainerBase, CorruptPartitionError, InvalidPartitionContainerError

if TYPE_CHECKING:
    from os import PathLike
    from typing import BinaryIO, Dict, Optional, Union

    from ...crypto import CryptoEngine
    from .cmac import CMACTypeBase
    from .common import ReadWriteBinaryFileModes, Partition


class DIFF(PartitionContainerBase):
    """
    Reads and writes to DIFF files.

    :param file: A file path or a file-like object with the DIFF data.
    :param mode: Mode to open the file with, passed to `open`. Only used if a file path was given.
    :param closefd: Close the underlying file object when closed. Defaults to `True` for file paths, and `False` for
        file-like objects.
    :param crypto: A custom :class:`~.CryptoEngine` object to be used. Defaults to None, which causes a new one to
        be created.
    :param dev: Use devunit keys.
    :param cmac_base: A :class:`~.CMACTypeBase` object that describes how to update the CMAC.
    :param sd_key_file: Path to a movable.sed file to load the SD KeyY from.
    :param sd_key: SD KeyY to use. Has priority over `sd_key_file` if both are specified.
    """

    partitions: 'Dict[int, Partition]'
    """Partitions of the file. DIFF only has one, so there would only be a single `0` key."""

    def __init__(self, file: 'Union[PathLike, str, bytes, BinaryIO]', mode: 'ReadWriteBinaryFileModes' = 'rb', *,
                 closefd: 'Optional[bool]' = None, crypto: 'CryptoEngine' = None, dev: bool = False,
                 cmac_base: 'CMACTypeBase' = None, sd_key_file: 'Union[PathLike, str, bytes]' = None,
                 sd_key: bytes = None):
        super().__init__(file, closefd=closefd, crypto=crypto, dev=dev, mode=mode, cmac_base=cmac_base,
                         sd_key_file=sd_key_file, sd_key=sd_key)

        self._file.seek(0xF0, 1)
        self._header = self._file.read(0x100)

        magic = self._header[0:8]
        if magic != b'DIFF\0\0\3\0':
            raise InvalidPartitionContainerError(f'DISA magic expected, got {magic}')

        secondary_partdesc_offset = readle(self._header[0x8:0x10])
        primary_partdesc_offset = readle(self._header[0x10:0x18])
        partdesc_size = readle(self._header[0x18:0x20])

        partition_a_offset = readle(self._header[0x20:0x28])
        partition_a_size = readle(self._header[0x28:0x30])

        active_partdesc = readle(self._header[0x30:0x34])

        active_partdesc_hash = self._header[0x34:0x54]

        if active_partdesc == 0:
            self._partdesc_offset = primary_partdesc_offset
        else:
            self._partdesc_offset = secondary_partdesc_offset

        self.unique_identifier = readle(self._header[0x54:0x5C])

        self._seek(self._partdesc_offset)
        partdesc = self._file.read(partdesc_size)
        if sha256(partdesc).digest() != active_partdesc_hash:
            raise CorruptPartitionError('Active partition table is corrupt')

        self._load_partition(0, partdesc, partition_a_offset, partition_a_size)

    def _update_hashes(self, partition: int, partdesc: bytes):
        """
        Update master hashes, partition descriptor hash, and CMAC.

        :param partition: Unused for DIFF. This exists for consistency with DISA.
        :param partdesc: Partition descriptor in bytes.
        """

        if self._file.writable():
            with self._lock:
                self._seek(self._partdesc_offset)
                self._file.write(partdesc)

                partdesc_hash = sha256(partdesc)

                header_ba = bytearray(self._header)
                header_ba[0x34:0x54] = partdesc_hash.digest()
                self._header = bytes(header_ba)

                self._seek(0x100)
                self._file.write(self._header)

                self._update_cmac()
