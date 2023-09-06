:mod:`romfs` - RomFS reader
===========================

.. py:module:: pyctr.type.romfs
    :synopsis: Read data from a Nintendo 3DS application RomFS

The :mod:`romfs` module enables reading application read-only filesystems.

RomFSReader objects
-------------------

.. autoclass:: RomFSReader
    :members: get_info_from_path
    :undoc-members:
    :show-inheritance:

    .. py:method:: open(path, mode='r', buffering=-1, encoding=None, errors=None, newline='', **options)

        Open a file for reading.

        .. warning::

            By default, for compatibility reasons, this function works differently than the normal FS open method.
            Files are opened in binary mode by default and ``mode`` accepts an encoding.
            This can be toggled off when creating the RomFSReader by passing ``open_compatibility_mode=False``.
            This compatibility layer will be removed in a future release.

        :param path: Path to a file.
        :type path: str
        :param buffering: Buffering policy (-1 to use default buffering, 0 to disable buffering, 1 to select line buffering, of any positive integer to indicate a buffer size).
        :type buffering: int
        :param encoding: Encoding for text files (defaults to ``utf-8``)
        :type encoding: str
        :param errors: What to do with unicode decode errors (see ``codecs`` module for more information).
        :type errors: Optional[str]
        :param newline: Newline parameter.
        :type newline: str
        :return: A file-like object.
        :rtype: SubsectionIO

Data classes
------------

.. autoclass:: RomFSDirectoryEntry
.. autoclass:: RomFSFileEntry

Exceptions
----------

.. autoexception:: RomFSError
.. autoexception:: InvalidIVFCError
.. autoexception:: InvalidRomFSHeaderError
.. autoexception:: RomFSEntryError
.. autoexception:: RomFSFileNotFoundError
.. autoexception:: RomFSIsADirectoryError
