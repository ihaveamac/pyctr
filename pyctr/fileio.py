# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from io import RawIOBase
from threading import Lock
from weakref import WeakValueDictionary
from typing import TYPE_CHECKING

from .common import _raise_if_file_closed, _raise_if_file_closed_generic

if TYPE_CHECKING:
    from typing import BinaryIO, Iterable, Tuple
    # this is to trick type checkers into accepting SubsectionIO as a BinaryIO object
    # if you know a better way, let me know
    RawIOBase = BinaryIO

# this prevents two SubsectionIO instances on the same file object from interfering with eachother
_lock_objects = WeakValueDictionary()


class SubsectionIO(RawIOBase):
    """
    Provides read-write access to a subsection of a file.

    :param file: A file-like object.
    :param offset: Offset of the section.
    :param size: Size of the section.
    """

    __slots__ = ('_end', '_lock', '_offset', '_reader', '_seek', '_size', 'closed')

    def __init__(self, file: 'BinaryIO', offset: int, size: int):
        self.closed = False
        self._seek = 0

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

    def __hash__(self):
        return hash((self._reader, self._offset, self._size, id(self)))

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

    @_raise_if_file_closed
    def flush(self) -> None:
        with self._lock:
            self._reader.flush()


class SplitFileMerger(RawIOBase):
    """
    Provides access to multiple file-like handles as one large file.

    :param files: A list of tuples with a file-like object and its size respectively.
    :param closefds: Close all file objects on close.
    :param read_only: If writing should be disabled.
    """

    __slots__ = ('_closefds', '_fake_seek', '_files', '_read_only', '_seek_info', '_total_size', 'closed')

    def __init__(self, files: 'Iterable[Tuple[BinaryIO, int]]', read_only: bool = True, closefds: bool = False):
        if not read_only:
            raise NotImplementedError('writing is not yet supported')

        self.closed = False

        # The seek over the current file, returned by tell().
        self._fake_seek = 0
        # Current file index and seek on it.
        self._seek_info = (0, 0)

        self._read_only = read_only
        self._closefds = closefds
        self._files = []
        curr_offset = 0

        for fh, size in files:
            self._files.append((fh, curr_offset, size))
            curr_offset += size

        self._total_size = curr_offset

    def _calc_seek(self, pos: int):
        self._fake_seek = pos
        for idx, info in enumerate(self._files):
            if info[1] <= pos < info[1] + info[2]:
                self._seek_info = (idx, pos - info[1])
                break

    def close(self):
        self.closed = True
        if self._closefds:
            for fh in self._files:
                fh[0].close()
        self._files = ()

    def __del__(self):
        self.close()

    @_raise_if_file_closed_generic
    def seek(self, pos: int, whence: int = 0):
        if whence == 0:
            if pos < 0:
                raise ValueError('negative seek value')
            self._calc_seek(pos)
        elif whence == 1:
            if self._fake_seek - pos < 0:
                pos = 0
            self._calc_seek(self._fake_seek + pos)
        elif whence == 2:
            if self._total_size + pos < 0:
                pos = -self._total_size
            self._calc_seek(self._total_size + pos)
        else:
            if isinstance(whence, int):
                raise ValueError(f'whence value {whence} unsupported')
            else:
                raise TypeError(f'an integer is required (got type {type(whence).__name__})')
        return self._fake_seek

    @_raise_if_file_closed_generic
    def tell(self) -> int:
        return self._fake_seek

    @_raise_if_file_closed_generic
    def read(self, n: int = -1) -> bytes:
        if n == -1:
            n = max(self._total_size - self._fake_seek, 0)
        elif self._fake_seek + n > self._total_size:
            n = max(self._total_size - self._fake_seek, 0)
        if n == 0:
            return b''

        left = n
        current_index = self._seek_info[0]

        full_data = []

        while True:
            info = self._files[current_index]
            fh = info[0]
            real_seek = self._fake_seek - info[1]
            to_read = min(info[2] - real_seek, left)

            fh.seek(real_seek)
            full_data.append(fh.read(to_read))
            self._fake_seek += to_read

            left -= to_read
            if left <= 0:
                break
            current_index += 1

        self._seek_info = (current_index, self._fake_seek - self._files[current_index][1])

        return b''.join(full_data)

    @_raise_if_file_closed_generic
    def write(self, s: bytes) -> int:
        raise NotImplementedError

    @_raise_if_file_closed_generic
    def readable(self) -> bool:
        return True

    @_raise_if_file_closed_generic
    def writable(self) -> bool:
        return not self._read_only

    @_raise_if_file_closed_generic
    def seekable(self) -> bool:
        return True


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
