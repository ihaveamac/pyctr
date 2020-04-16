# This file is a part of pyctr.
#
# Copyright (c) 2017-2020 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from functools import wraps
from typing import TYPE_CHECKING, NamedTuple

from ....common import PyCTRError
from ....util import readle, roundup

if TYPE_CHECKING:
    from typing import BinaryIO


class PartitionDescriptorError(PyCTRError):
    """Generic error for operations related to DIFI, IVFC, or DPFS."""


class InvalidHeaderError(PartitionDescriptorError):
    """The header is invalid."""


class InvalidHeaderLengthError(InvalidHeaderError):
    """Length of the header is invalid."""


class LevelData(NamedTuple):
    """Level data used by IVFC and DPFS."""

    offset: int
    """Offset of the level."""
    size: int
    """Size of the final level."""
    block_size_log2: int
    """Block size in log2."""
    block_size: int
    """Actual block size."""


def get_block_range(offset: int, size: int, block_size: int):
    starting_block = (roundup(offset - block_size + 1, block_size)) // block_size

    ending_block = max(((roundup(offset + size, block_size)) // block_size) - 1, starting_block)

    return starting_block, ending_block


def read_le_u32_array(data: bytes):
    """Yields each little-endian u32 in a block of data."""
    for o in range(0, len(data), 4):
        yield readle(data[o:o+4])


def _raise_if_level_closed(method):
    @wraps(method)
    def decorator(self: 'BinaryIO', *args, **kwargs):
        if self.closed:
            raise ValueError('I/O operation on closed file')
        return method(self, *args, **kwargs)
    return decorator
