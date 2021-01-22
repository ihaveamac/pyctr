# This file is a part of pyctr.
#
# Copyright (c) 2017-2021 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from io import RawIOBase
from threading import Lock
from weakref import WeakValueDictionary
from typing import TYPE_CHECKING

from .common import _raise_if_file_closed

if TYPE_CHECKING:
    from typing import BinaryIO, IO
    # this is to trick type checkers into accepting SubsectionIO as a BinaryIO object
    # if you know a better way, let me know
    RawIOBase = BinaryIO

# this prevents two SubsectionIO instances on the same file object from interfering with eachother
_lock_objects = WeakValueDictionary()


class SubsectionIO(RawIOBase):
    """Provides read-write access to a subsection of a file."""

    closed = False
    _seek = 0

    def __init__(self, file: 'BinaryIO', offset: int, size: int):
        # get existing Lock object for file, or create a new one
        file_id = id(file)
        try:
            self._lock = _lock_objects[file_id]
        except KeyError:
            self._lock = Lock()
            _lock_objects[file_id] = self._lock

        self._reader = file
        self._offset = offset
        self._size = size
        # subsection end is stored for convenience
        self._end = offset + size

    def __repr__(self):
        return f'{type(self).__name__}(file={self._reader!r}, offset={self._offset!r}, size={self._size!r})'

    def close(self):
        self.closed = True
        # remove Lock reference, so it can be automatically removed from the WeakValueDictionary once all SubsectionIO
        #   instances for the base file are closed
        self._lock = None

    __del__ = close

    @_raise_if_file_closed
    def read(self, size: int = -1) -> bytes:
        if size == -1:
            size = self._size - self._seek
        if self._offset + self._seek > self._end:
            # if attempting to read after the section, return nothing
            return b''
        if self._seek + size > self._size:
            size = self._size - self._seek
           
        with self._lock:
            self._reader.seek(self._seek + self._offset)
            data = self._reader.read(size)

        self._seek += len(data)
        return data

    @_raise_if_file_closed
    def seek(self, seek: int, whence: int = 0) -> int:
        if whence == 0:
            if seek < 0:
                raise ValueError(f'negative seek value {seek}')
            self._seek = min(seek, self._size)
        elif whence == 1:
            self._seek = max(self._seek + seek, 0)
        elif whence == 2:
            self._seek = max(self._size + seek, 0)
        else:
            if not isinstance(whence, int):
                raise TypeError(f'an integer is required (got type {type(whence).__name__}')
            raise ValueError(f'invalid whence ({seek}, should be 0, 1 or 2)')
        return self._seek

    @_raise_if_file_closed
    def write(self, data: bytes) -> int:
        if self._seek > self._size:
            # attempting to write past subsection
            return 0
        data_len = len(data)
        data_end = data_len + self._seek
        if data_end > self._size:
            data = data[:-(data_end - self._size)]

        with self._lock:
            self._reader.seek(self._seek + self._offset)
            data_written = self._reader.write(data)

        self._seek += data_written
        return data_written

    @_raise_if_file_closed
    def readable(self) -> bool:
        return self._reader.readable()

    @_raise_if_file_closed
    def writable(self) -> bool:
        return self._reader.writable()

    @_raise_if_file_closed
    def seekable(self) -> bool:
        return self._reader.seekable()


class CloseWrapper(RawIOBase):
    """
    Wrapper around a file object that prevents closing the original object.

    For example, in :class:`~.CDNReader`, one :class:`~.CBCFileIO` object is used per content. If this is closed, it
    affects future uses of the same content.
    """

    closed = False

    def __init__(self, file: 'BinaryIO'):
        self._reader = file

    def __repr__(self):
        return f'{type(self).__name__}({self._reader!r})'

    def close(self) -> None:
        self.closed = True

    __del__ = close

    @_raise_if_file_closed
    def read(self, n: int = -1) -> bytes:
        return self._reader.read(n)

    @_raise_if_file_closed
    def write(self, s: bytes) -> int:
        return self._reader.write(s)

    @_raise_if_file_closed
    def seek(self, offset: int, whence: int = 0) -> int:
        return self._reader.seek(offset, whence)

    @_raise_if_file_closed
    def readable(self) -> bool:
        return self.readable()

    @_raise_if_file_closed
    def writable(self) -> bool:
        return self.writable()

    @_raise_if_file_closed
    def seekable(self) -> bool:
        return self.seekable()
