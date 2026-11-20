# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

"""Module for interacting with encrypted SD card contents under the "Nintendo 3DS" directory."""

from os import fsdecode
from os.path import join, basename

from typing import TYPE_CHECKING

from fsspec import AbstractFileSystem
from fsspec.implementations.dirfs import DirFileSystem

from ..common import PyCTRError
from ..crypto import CryptoEngine, KeyslotMissingError, Keyslot
from .sdtitle import SDTitleReader
from .save.disa import DISA
from .save.fat.save import InnerFATSAVE

if TYPE_CHECKING:
    from typing import BinaryIO
    from ..common import FilePath, DirPathOrFS


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

    def __init__(self, path: 'DirPathOrFS', *, crypto: CryptoEngine = None,
                 dev: bool = False, sd_key_file: 'FilePath' = None, sd_key: bytes = None):
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

        if isinstance(path, AbstractFileSystem):
            self.fs = path
        else:
            self.fs = DirFileSystem(fsdecode(path))

        self.id1s = []
        for id1 in self.fs.ls(self.id0, detail=False):
            id1 = basename(id1)
            try:
                # check if it decodes to hex
                bytes.fromhex(id1)
            except ValueError:
                pass
            else:
                if len(id1) == 32:
                    self.id1s.append(id1)

        if len(self.id1s) == 0:
            raise MissingID1Error('could not find any ID1 directories in ' + self._crypto.id0.hex())

    def open_id1(self, /, id1: 'str | None' = None):
        if not id1:
            id1 = self.id1s[0]
        return SDFS(self.id0 + '/' + id1, self.fs, crypto=self._crypto)

    def open_title(self, /, title_id: str, *, case_insensitive: bool = False, seed: bytes = None,
                   load_contents: bool = True, id1: 'str | None' = None):
        fs = self.open_id1(id1)
        title_id = title_id.lower()
        sd_path = f'/title/{title_id[0:8]}/{title_id[8:16]}/content'

        tmds = []
        for f in fs.ls(sd_path, detail=False):
            if f.endswith('.tmd'):
                tmds.append(f)

        if not tmds:
            raise MissingTitleError(title_id)

        # In case there is an in-progress download here, we choose the tmd with the smaller number,
        # so we can get the active title
        tmds.sort(key=lambda x: int(basename(x)[0:8]))

        return SDTitleReader(join(sd_path, tmds[0]), case_insensitive=case_insensitive, fs=fs,
                             dev=self._crypto.dev, seed=seed, load_contents=load_contents)

    def open_save(self, /, title_id: str, mode: str = 'rb', *, id1: 'Optional[str]' = None) -> 'InnerFATSAVE':
        if 'w' in mode or '+' in mode:
            raise NotImplementedError('writing to saves is not implemented yet')
        fs = self.open_id1(id1)
        title_id = title_id.lower()
        sd_path = f'/title/{title_id[0:8]}/{title_id[8:16]}/data/00000001.sav'

        disa = DISA(sd_path, mode, fs=fs, closefd=True)
        lv4p1 = disa.partitions[0].file
        try:
            lv4p2 = disa.partitions[1].file
        except IndexError:
            lv4p2 = None

        return InnerFATSAVE(lv4p1, lv4p2, closefd=True, container=disa)

class SDFS(DirFileSystem):
    """
    Enables access to an SD card filesystem inside Nintendo 3DS/id0/id1.

    Currently, files under "Nintendo DSiWare" cannot be opened.

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

    def __init__(self, path: str, fs: 'AbstractFileSystem', *, crypto: CryptoEngine):
        super().__init__(path, fs)
        self._crypto = crypto

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def open(
        self,
        path,
        mode="rb",
        *args,
        **kwargs,
    ) -> 'BinaryIO':
        if 't' in mode:
            raise NotImplementedError('text mode is not supported')
        if 'Nintendo DSiWare' in path:
            raise NotImplementedError('files under "Nintendo DSiWare" currently cannot be opened with this method')
        base_file = super()._open(path, mode, *args, **kwargs)
        if path[0] != '/':
            path = '/' + path
        # the previous version using pyfilesystem2 used normpath and abspath
        # I don't remember why exactly
        return self._crypto.create_ctr_io(Keyslot.SD, base_file, self._crypto.sd_path_to_iv(path), closefd=True)

    def mv(self, path1, path2, **kwargs):
        raise NotImplementedError('renaming files is not allowed in SDFS')
