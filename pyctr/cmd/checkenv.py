# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full licese text in LICENSE in the root of this project.

from hashlib import sha256
from os import environ
from os.path import join, isfile
from typing import TYPE_CHECKING

from ..crypto.engine import BOOT9_PROT_HASH, b9_paths
from ..crypto.seeddb import seeddb_paths
from ..util import config_dirs

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace


def find_boot9():
    results = {}
    for p in b9_paths:
        result = {'type': 'unknown', 'valid': False}
        try:
            with open(p, 'rb') as f:
                data = f.read(0x10000)
        except FileNotFoundError:
            pass
        else:
            if len(data) == 0x10000:
                # trim full boot9 to just prot
                data = data[0x8000:]
                result['type'] = 'full'
            elif len(data) == 0x8000:
                result['type'] = 'prot'
            b9_sha = sha256(data)
            if b9_sha.hexdigest() == BOOT9_PROT_HASH:
                result['valid'] = True
            results[p] = result

    return results


def find_seeddb():
    found = []
    for p in seeddb_paths:
        if isfile(p):
            found.append(p)

    return found


def main(parser: 'ArgumentParser', args: 'Namespace'):
    b9_results = find_boot9()
    if b9_results:
        print('boot9 status:')
        for path, result in b9_results.items():
            if result['valid'] is not None:
                print(f' - {path}: type: {result["type"]}, valid: {result["valid"]}')
    else:
        print('boot9 not found. Put it in one of these paths:')
        for p in b9_paths:
            print(' -', p)
        print(' - BOOT9_PATH (environment variable)')

    seeddb_results = find_seeddb()
    if seeddb_results:
        print('seeddb status:')
        for path in seeddb_results:
            print(' -', path)
    else:
        print('seeddb not found. Put it in one of these paths:')
        for p in seeddb_paths:
            print(' -', p)
        print(' - SEEDDB_PATH (environment variable)')
