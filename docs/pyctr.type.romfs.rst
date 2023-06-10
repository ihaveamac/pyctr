:mod:`romfs` - RomFS reader
===========================

.. py:module:: pyctr.type.romfs
    :synopsis: Read data from a Nintendo 3DS application RomFS

The :mod:`romfs` module enables reading application read-only filesystems.

RomFSReader objects
-------------------

.. autoclass:: RomFSReader
    :members: open, get_info_from_path
    :undoc-members:
    :show-inheritance:

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
