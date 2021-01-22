# This file is a part of pyctr.
#
# Copyright (c) 2017-2021 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from threading import Lock
from typing import TYPE_CHECKING

from ...common import PyCTRError
from ...fileio import SubsectionIO
from ..base import TypeReaderCryptoBase
from .partition import Partition, load_partdesc

if TYPE_CHECKING:
    from os import PathLike
    from typing import BinaryIO, Dict, Literal, Optional, Union

    from ...crypto import CryptoEngine
    from .cmac import CMACTypeBase

    ReadWriteBinaryFileModes = Literal['rb', 'br', 'rb+', 'br+', 'b+r', 'r+b', '+rb', '+br']


class PartitionContainerError(PyCTRError):
    """Generic error for partition container operations."""


class InvalidPartitionContainerError(PartitionContainerError):
    """There is an error with the header, such as a missing magic."""


class CorruptPartitionError(PartitionContainerError):
    """A hash somewhere in the header is incorrect."""


class PartitionContainerBase(TypeReaderCryptoBase):
    """
    Base class for the DISA and DIFF classes.

    This object is not to be manually created. Please use the :class:`~.DISA` or :class:`~.DIFF` classes.

    :param file: A file path or a file-like object with the DISA or DIFF data.
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
    """Partitions of the file. Only 0 exists for DIFF, while 0 and 1 can exist with DISA."""

    _header: bytes
    """Raw header for CMAC generation."""

    def __init__(self, file: 'Union[PathLike, str, bytes, BinaryIO]', mode: 'ReadWriteBinaryFileModes' = 'rb', *,
                 closefd: 'Optional[bool]' = None, crypto: 'CryptoEngine' = None, dev: bool = False,
                 cmac_base: 'CMACTypeBase' = None, sd_key_file: 'Union[PathLike, str, bytes]' = None,
                 sd_key: bytes = None):
        super().__init__(file, closefd=closefd, mode=mode, crypto=crypto, dev=dev)

        self.cmac = self._file.read(0x10)

        if sd_key:
            self._crypto.setup_sd_key(sd_key)
        elif sd_key_file:
            self._crypto.setup_sd_key_from_file(sd_key_file)

        self._cmac_base = cmac_base
        if self._cmac_base:
            self._cmac_base.set_crypto(self._crypto)

        self._lock = Lock()

        self.partitions = {}

    def _load_partition(self, index: int, partdesc: bytes, partition_offset: int, partition_size: int):
        subfile = SubsectionIO(self._file, partition_offset, partition_size)

        difi, ivfc, dpfs, master_hash = load_partdesc(partdesc)

        def callback(new_partdesc: bytes):
            return self._update_hashes(index, new_partdesc)

        partition = Partition(subfile, difi, ivfc, dpfs, master_hash, update_partdesc_callback=callback,
                              partdesc_size=len(partdesc))

        self.partitions[index] = partition

    def _update_hashes(self, index: int, partdesc: bytes):
        """Dummy function since DISA and DIFF should be defining this."""
        raise NotImplementedError

    def _update_cmac(self):
        """Update the CMAC of the file. Both DISA and DIFF put this at offset 0."""
        if self._cmac_base:
            self.cmac = self._cmac_base.generate_cmac(self._header)
            self._seek(0)
            self._file.write(self.cmac)
