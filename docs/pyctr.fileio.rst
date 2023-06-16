:mod:`fileio` - Special files
=============================

.. py:module:: pyctr.fileio
    :synopsis: Provides special file objects

This module contains some special file objects.

Classes
-------

.. py:class:: pyctr.fileio.SubsectionIO(file, offset, size)

    Provides read-write access to a subsection of a file. Data written after the end is discarded.

    This class is thread-safe with other :class:`SubsectionIO` objects. A thread lock is stored for each base file, meaning two :class:`SubsectionIO` objects on one base file will use locks to prevent issues, while two with different base files can operate independently.

    However this cannot protect against threaded access from somewhere else. If another function seeks, reads, or writes data to the base file at the same time, it could interfere and read or write the wrong data.

    Available methods: ``close``, ``read``, ``seek``, ``tell``, ``write``, ``readable``, ``writable``, ``seekable``, ``flush``.

    :param file: Base file.
    :type file: :term:`binary file`
    :param offset: Offset of the section.
    :type offset: int
    :param size: Size of the section.
    :type size: int

.. py:class:: pyctr.fileio.SplitFileMerger(files, read_only=True, closefds=False)

    Provides access to multiple file objects as one large file.

    This is not thread-safe with other :class:`SplitFileMerger` objects.

    .. note::

        Writing is not implemented yet.

    Available methods: ``close``, ``read``, ``seek``, ``tell``, ``write``, ``readable``, ``writable``, ``seekable``.

    :param files: A list of tuples with binary files and size.
    :type files: Iterable[Tuple[(:term:`binary file`), int]]
    :param read_only: Disable writing.
    :type read_only: bool
    :param closefds: Close all file objects when this is closed.
    :type closefds: bool
