# This file is a part of pyctr.
#
# Copyright (c) 2017-2020 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

"""Module for interacting with encrypted SD card contents under the "Nintendo 3DS" directory."""

from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING

from ..common import PyCTRError
from ..crypto import CryptoEngine, KeyslotMissingError, Keyslot

if TYPE_CHECKING:
    # noinspection PyProtectedMember
    from ..crypto import CTRFileIO
    from typing import BinaryIO, Union


class SDFilesystemError(PyCTRError):
    """Generic exception for SD filesystem operations."""


class MissingMovableSedError(SDFilesystemError):
    """movable.sed key is not set up."""


class MissingID0Error(SDFilesystemError):
    """ID0 directory could not be found."""


class MissingID1Error(SDFilesystemError):
    """No ID1 directories exist in the ID0 directory."""


def normalize_sd_path(path: str):
    return path.lstrip('/').lstrip('\\')


class SDFilesystem:
    """
    Allows access to encrypted SD card contents under the "Nintendo 3DS" directory.

    :param path: Path to the Nintendo 3DS folder.
    :param crypto: A custom :class:`crypto.CryptoEngine` object to be used. Defaults to None, which causes a new one to
        be created.
    :param sd_key_file: Path to a movable.sed file to load the SD KeyY from.
    :param sd_key: SD KeyY to use. Has priority over `sd_key_file` if both are specified.
    :ivar id1s: A list of ID1 directories found in the ID0 directory.
    :ivar current_id1: The ID1 directory used as the default when none is specified, initially set to the first value
        in id1s.
    """

    def __init__(self, path: 'Union[PathLike, str, bytes]', *, crypto: CryptoEngine = None, dev: bool = False,
                 sd_key_file: 'Union[PathLike, str, bytes]' = None, sd_key: bytes = None):
        if crypto:
            self._crypto = crypto
        else:
            self._crypto = CryptoEngine(dev=dev)

        if sd_key:
            self._crypto.setup_sd_key(sd_key)
        elif sd_key_file:
            self._crypto.setup_sd_key_from_file(sd_key_file)

        self._base_path = Path(path)

        try:
            self._id0_path = self._base_path / self._crypto.id0.hex()
        except KeyslotMissingError:
            raise MissingMovableSedError('set up key with sd_key_file or sd_key')

        if not self._id0_path.is_dir():
            raise MissingID0Error(self._crypto.id0.hex())

        self.id1s = []
        for id1 in self._id0_path.iterdir():
            try:
                # check if it decodes to hex
                bytes.fromhex(id1.name)
            except ValueError:
                pass
            else:
                if len(id1.name) == 32:
                    self.id1s.append(id1.name)

        if len(self.id1s) == 0:
            raise MissingID1Error('could not find any ID1 directories in ' + self._crypto.id0.hex())

        self.current_id1 = self.id1s[0]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def _get_real_path(self, path: str, id1: str = None):
        if not id1:
            id1 = self.current_id1
        return self._id0_path / id1 / path

    def open(self, path: str, mode: str = 'rb', *, id1: str = None) -> 'CTRFileIO':
        """
        Opens a file in the SD filesystem, allowing decrypted access.

        Currently, files under "Nintendo DSiWare" cannot be opened.

        :param path: Path relative to the ID1 directory.
        :param mode: Mode to open the file with. Binary mode is always used.
        :param id1: ID1 directory to use. Defaults to current_id1.
        :return: A file-like object which decrypts and encrypts on the fly.
        :rtype: CTRFileIO
        """
        # The way DSiWare exports are encrypted makes it annoying to do crypto on the fly.
        # A different method would have to be used to support them.
        if 'Nintendo DSiWare' in path:
            raise NotImplementedError('files under "Nintendo DSiWare" currently cannot be opened with this method')

        if not id1:
            id1 = self.id1s[0]

        if 'b' not in mode:
            # force binary mode, since the 3DS does not use text files here
            mode += 'b'

        path = normalize_sd_path(path)
        real_path = self._get_real_path(path, id1)

        # since we're forcing opening in binary mode, we can assume this will be BinaryIO
        # noinspection PyTypeChecker
        fh: BinaryIO = real_path.open(mode)
        return self._crypto.create_ctr_io(Keyslot.SD, fh, self._crypto.sd_path_to_iv('/' + path))

    def listdir(self, path: str, id1: str = None) -> list:
        """
        Returns a list of files in the directory.

        :param path: Directory to list the contents of.
        :param id1: ID1 directory to use. Defaults to current_id1.
        :return: A list of files in the directory.
        :rtype: list
        """
        real_path = self._get_real_path(normalize_sd_path(path), id1)
        return list(x.name for x in real_path.iterdir())
