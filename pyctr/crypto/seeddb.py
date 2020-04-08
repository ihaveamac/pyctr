# This file is a part of pyctr.
#
# Copyright (c) 2017-2020 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from os import PathLike, environ
from os.path import join
from types import MappingProxyType
from typing import TYPE_CHECKING

from ..common import PyCTRError
from ..util import config_dirs, readle

if TYPE_CHECKING:
    from typing import BinaryIO, Dict, Union

__all__ = ['SeedDBError', 'InvalidProgramIDError', 'InvalidSeedError', 'MissingSeedError', 'load_seeddb', 'get_seed',
           'add_seed', 'get_all_seeds', 'save_seeddb']

SEED_ENTRY_PADDING = (b'\0' * 8)


class SeedDBError(PyCTRError):
    """Generic exception for seed operations."""


class InvalidProgramIDError(SeedDBError):
    """Program ID is not in a valid format."""


class InvalidSeedError(SeedDBError):
    """The provided seed is not in a valid format."""


class MissingSeedError(SeedDBError):
    """Seed not found in the database."""


_seeds: 'Dict[int, bytes]' = {}
_loaded_from_default_paths = False


def _load_seeds_from_file_object(fh: 'BinaryIO'):
    seed_count = readle(fh.read(4))
    fh.seek(0x10)
    for _ in range(seed_count):
        entry = fh.read(0x20)
        title_id = readle(entry[0:8])
        _seeds[title_id] = entry[0x8:0x18]


def _normalize_program_id(program_id: 'Union[int, str, bytes]') -> int:
    if not isinstance(program_id, (int, str, bytes)):
        raise InvalidProgramIDError('not an int, str, or bytes')

    if isinstance(program_id, str):
        program_id = int(program_id, 16)
    elif isinstance(program_id, bytes):
        program_id = int.from_bytes(program_id, 'little')

    return program_id


def load_seeddb(fp: 'Union[PathLike, str, bytes, BinaryIO]' = None):
    """
    Load a seeddb file.

    :param fp: A file path or file-like object with the seeddb data.
    """
    global _loaded_from_default_paths
    if fp:
        if isinstance(fp, (PathLike, str, bytes)):
            fp = open(fp, 'rb')
        _load_seeds_from_file_object(fp)
    elif not _loaded_from_default_paths:
        seeddb_paths = [join(x, 'seeddb.bin') for x in config_dirs]
        try:
            # try to insert the path in the SEEDDB_PATH environment variable
            seeddb_paths.insert(0, environ['SEEDDB_PATH'])
        except KeyError:
            pass

        for path in seeddb_paths:
            try:
                with open(path, 'rb') as fh:
                    _load_seeds_from_file_object(fh)
            except FileNotFoundError:
                pass

        _loaded_from_default_paths = True


def get_seed(program_id: 'Union[int, str, bytes]', *, load_if_required: bool = True):
    """
    Get a seed for a Program ID.

    :param program_id: The Program ID to search for. If `bytes` is provided, the value must be little-endian.
    :param load_if_required: Automatically load using :func:`load_seeddb` if the requested Program ID is not already
        available.
    """
    program_id = _normalize_program_id(program_id)

    try:
        return _seeds[program_id]
    except KeyError:
        if _loaded_from_default_paths or not load_if_required:
            raise MissingSeedError(f'{program_id:016x}')
        else:
            if load_if_required:
                load_seeddb()
                return get_seed(program_id, load_if_required=False)


def add_seed(program_id: 'Union[int, str, bytes]', seed: 'Union[bytes, str]'):
    """
    Adds a seed to the database.

    :param program_id: The Program ID associated with the seed. If `bytes` is provided, the value must be little-endian.
    :param seed: The seed to add.
    """
    program_id = _normalize_program_id(program_id)

    if isinstance(seed, str):
        try:
            seed = bytes.fromhex(seed)
        except ValueError:
            raise InvalidSeedError('seed is not in hex')

    if len(seed) != 16:
        raise InvalidSeedError(f'expected 16 bytes, got {len(seed)}')

    _seeds[program_id] = seed


def get_all_seeds():
    """
    Gets all the loaded seeds.

    :return: A read-only view of the seed database.
    """
    return MappingProxyType(_seeds)


def save_seeddb(fp: 'Union[PathLike, str, bytes, BinaryIO]'):
    """
    Save the seed database to a seeddb file.

    :param fp: A file path or file-like object to write the seeddb data to.
    """
    if isinstance(fp, (PathLike, str, bytes)):
        fp = open(fp, 'wb')

    fp.write(len(_seeds).to_bytes(4, 'little') + (b'\0' * 12))

    for program_id, seed in _seeds.items():
        fp.write(program_id.to_bytes(8, 'little') + seed + SEED_ENTRY_PADDING)
