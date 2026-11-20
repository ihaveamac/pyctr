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

    .. py:method:: open(path, mode="rb", block_size=None, cache_options=None, compression=None, **kwargs)

        Open a file for reading.

        :param path: Path to a file.
        :type path: str
        :param block_size: Currently unused.
        :param cache_options: Currently unused.
        :param compression: Currently unused.
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
