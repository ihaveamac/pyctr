# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

"""Module for interacting with encrypted SD card contents under the "Nintendo 3DS" directory."""

from os import fsdecode
from typing import TYPE_CHECKING

from fs import open_fs
from fs.base import FS
from fs.subfs import SubFS
from fs.path import abspath, normpath, join

from ..common import PyCTRError
from ..crypto import CryptoEngine, KeyslotMissingError, Keyslot
from .sdtitle import SDTitleReader

if TYPE_CHECKING:
    from os import PathLike
    from typing import BinaryIO, Mapping, Optional
    from ..common import FilePath, DirPathOrFS

    # noinspection PyProtectedMember
    from ..crypto import CTRFileIO


class SDFilesystemError(PyCTRError):
    """Generic exception for SD filesystem operations."""


class MissingMovableSedError(SDFilesystemError):
    """movable.sed key is not set up."""


class MissingID0Error(SDFilesystemError):
    """ID0 directory could not be found."""


class MissingID1Error(SDFilesystemError):
    """No ID1 directories exist in the ID0 directory."""


class MissingTitleError(SDFilesystemError):
    """The requested Title ID could not be found."""


class SDRoot:
    """
    Opens an ID0 folder inside a "Nintendo 3DS" folder.

    :param path: Path to the Nintendo 3DS folder.
    :param crypto: A custom :class:`crypto.CryptoEngine` object to be used. Defaults to None, which causes a new one to
        be created.
    :param sd_key_file: Path to a movable.sed file to load the SD KeyY from.
    :param sd_key: SD KeyY to use. Has priority over `sd_key_file` if both are specified.
    :ivar id1s: A list of ID1 directories found in the ID0 directory.
    """

    def __init__(self, path: 'DirPathOrFS', *, crypto: CryptoEngine = None, dev: bool = False,
                 sd_key_file: 'FilePath' = None, sd_key: bytes = None):
        if crypto:
            self._crypto = crypto
        else:
            self._crypto = CryptoEngine(dev=dev)

        if sd_key:
            self._crypto.setup_sd_key(sd_key)
        elif sd_key_file:
            self._crypto.setup_sd_key_from_file(sd_key_file)

        try:
            self.id0 = self._crypto.id0.hex()
        except KeyslotMissingError:
            raise MissingMovableSedError('set up key with sd_key_file or sd_key')

        if isinstance(path, FS):
            self.fs = path
        else:
            self.fs = open_fs(fsdecode(path))

        self.id1s = []
        for id1 in self.fs.scandir(self.id0):
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

    def open_id1(self, /, id1: 'Optional[str]' = None):
        if not id1:
            id1 = self.id1s[0]
        return self.fs.opendir(self.id0 + '/' + id1, lambda p, f: SDFS(p, f, crypto=self._crypto))

    def open_title(self, /, title_id: str, *, case_insensitive: bool = False, seed: bytes = None,
                   load_contents: bool = True, id1: 'Optional[str]' = None):
        fs = self.open_id1(id1)
        title_id = title_id.lower()
        sd_path = f'/title/{title_id[0:8]}/{title_id[8:16]}/content'

        tmds = []
        for f in fs.listdir(sd_path):
            if f.endswith('.tmd'):
                tmds.append(f)

        if not tmds:
            raise MissingTitleError(title_id)

        # In case there is an in-progress download here, we choose the tmd with the smaller number,
        # so we can get the active title
        tmds.sort(key=lambda x: int(x[0:8]))

        return SDTitleReader(join(sd_path, tmds[0]), case_insensitive=case_insensitive, fs=fs,
                             dev=self._crypto.dev, seed=seed, load_contents=load_contents)


class SDFS(SubFS):
    """
    Enables access to an SD card filesystem inside Nintendo 3DS/id0/id1.

    :param path: Path to the Nintendo 3DS folder.
    :param crypto: A custom :class:`crypto.CryptoEngine` object to be used. Defaults to None, which causes a new one to
        be created.
    :param sd_key_file: Path to a movable.sed file to load the SD KeyY from.
    :param sd_key: SD KeyY to use. Has priority over `sd_key_file` if both are specified.
    :ivar id1s: A list of ID1 directories found in the ID0 directory.
    :ivar current_id1: The ID1 directory used as the default when none is specified, initially set to the first value
        in id1s.
    """

    __slots__ = ('_base_path', '_crypto', '_id0_path', 'current_id1', 'id1s')

    def __init__(self, parent_fs: 'FS', path: str, *, crypto: CryptoEngine):
        super().__init__(parent_fs, path)
        self._crypto = crypto

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def openbin(self, path: str, mode: str = 'r', buffering: int = -1, **options) -> 'BinaryIO':
        """
        Opens a file in the SD filesystem, allowing decrypted access.

        Currently, files under "Nintendo DSiWare" cannot be opened.

        :param path: Path relative to the ID1 directory.
        :param mode: Mode to open the file with.
        :param buffering: Buffering policy (-1 to use default buffering, 0 to disable buffering,
            1 to select line buffering, of any positive integer to indicate a buffer size).
        :return: A file-like object which decrypts and encrypts on the fly.
        :rtype: CTRFileIO
        """
        # The way DSiWare exports are encrypted makes it annoying to do crypto on the fly.
        # A different method would have to be used to support them.
        if 'Nintendo DSiWare' in path:
            raise NotImplementedError('files under "Nintendo DSiWare" currently cannot be opened with this method')

        fh = super().openbin(path, mode, buffering, **options)
        return self._crypto.create_ctr_io(Keyslot.SD, fh, self._crypto.sd_path_to_iv(normpath(abspath(path))),
                                          closefd=True)

    def open(
        self,
        path,
        mode: str = 'rb',
        buffering: int = -1,
        encoding: 'Optional[str]' = None,
        errors: 'Optional[str]' = None,
        newline: str = '',
        **options
    ) -> 'BinaryIO':
        if 'b' not in mode:
            mode += 'b'
        if 't' in mode:
            raise NotImplementedError('text mode is not supported')
        # noinspection PyTypeChecker
        return self.openbin(path, mode, buffering, **options)

    def getmeta(self, namespace: str = 'standard') -> 'Mapping[str, object]':
        meta = dict(super().getmeta(namespace))
        meta['supports_rename'] = False
        return meta
