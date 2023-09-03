# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from argparse import ArgumentParser
from sys import argv, version as pyver
from typing import TYPE_CHECKING

from .. import __version__
from .checkenv import main as checkenv_main

if TYPE_CHECKING:
    from typing import Optional
    from argparse import Namespace


def print_version(detail: int):
    if detail == 1:
        print('pyctr ' + __version__)
    elif detail >= 2:
        pyver_short = pyver.split()[0]
        print('pyctr ' + __version__ + ' running on Python ' + pyver_short)


def create_argparser(prog):
    p = ArgumentParser(prog=prog, description='Interact with Nintendo 3DS files')

    p.add_argument('--version', '-V', action='count', help='Print version')

    subparsers = p.add_subparsers(metavar='command')
    checkenv_sp = subparsers.add_parser('checkenv', help='check pyctr environment', description='check pyctr environment')
    checkenv_sp.set_defaults(func=checkenv_main)

    return p


def main(args: 'Optional[list[str]]' = None):
    if not args:
        args = argv[1:]

    p = create_argparser('pyctr.cmd')
    a = p.parse_args(args=args)

    if a.version:
        print_version(a.version)
        return

    if 'func' not in a:
        p.print_help()
        return

    a.func(p, a)


if __name__ == '__main__':
    main()
