# This file is a part of pyctr.
#
# Copyright (c) 2017-2020 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from functools import wraps
from os import PathLike
from typing import TYPE_CHECKING

from ...common import PyCTRError
from ...crypto import CryptoEngine

if TYPE_CHECKING:
    from typing import BinaryIO, Optional, Union

__all__ = ['raise_if_closed', 'ReaderError', 'ReaderClosedError', 'TypeReaderBase', 'TypeReaderCryptoBase']


def raise_if_closed(method):
    """
    Wraps a method that raises an exception if the reader object is closed.

    :param method: The method to call if the file is not closed.
    :return: The wrapper method.
    """
    @wraps(method)
    def decorator(self: 'TypeReaderBase', *args, **kwargs):
        if self.closed:
            raise ValueError('I/O operation on closed file')
        return method(self, *args, **kwargs)
    return decorator


class ReaderError(PyCTRError):
    """Generic error for TypeReaderBase operations."""


class ReaderClosedError(ReaderError):
    """The reader object is closed."""


class TypeReaderBase:
    """
    Base class for all reader classes.

    This handles types that are based in a single file. Therefore not every class will use this, such as SDFilesystem.

    :param file: A file path or a file-like object with the type's data.
    :param closefd: Close the underlying file object when closed. Defaults to `True` for file paths, and `False` for
        file-like objects.
    """

    closed = False
    """`True` if the reader is closed."""

    def __init__(self, file: 'Union[PathLike, str, bytes, BinaryIO]', *, closefd: 'Optional[bool]' = None):
        # Determine whether or not fp is a path or not.
        default_closefd = False
        if isinstance(file, (PathLike, str, bytes)):
            file = open(file, 'rb')
            default_closefd = True

        if closefd is None:
            closefd = default_closefd

        self._closefd = closefd

        # Store the file in a private attribute.
        self._file = file

        # Store the starting offset of the file.
        self._start = file.tell()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close the reader. If closefd is `True`, the underlying file is also closed."""
        if not self.closed:
            self.closed = True
            if self._closefd:
                try:
                    self._file.close()
                except AttributeError:
                    pass

    __del__ = close


class TypeReaderCryptoBase(TypeReaderBase):
    """
    Base class for reader classes that use a :class:`~.CryptoEngine` object..

    :param file: A file path or a file-like object with the type's data.
    :param closefd: Close the underlying file object when closed. Defaults to `True` for file paths, and `False` for
        file-like objects.
    :param dev: Use devunit keys.
    """

    def __init__(self, file: 'Union[PathLike, str, bytes, BinaryIO]', *, closefd: bool = None,
                 crypto: 'CryptoEngine' = None, dev: bool = False):
        super().__init__(file, closefd=closefd)

        if crypto:
            self._crypto = crypto
        else:
            self._crypto = CryptoEngine(dev=dev)
