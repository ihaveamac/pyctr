:mod:`exefs` - ExeFS reader
===========================

.. py:module:: pyctr.type.exefs
    :synopsis: Read data from a Nintendo 3DS application ExeFS

The :mod:`exefs` module enables reading application executable filesystems.

ExeFSReader objects
-------------------

.. autoclass:: ExeFSReader
    :members: open, decompress_code, icon, entries
    :undoc-members:
    :show-inheritance:

Data classes
------------

.. autoclass:: ExeFSEntry

Functions
---------

.. autofunction:: decompress_code

    Decompress the given code. This is called by :meth:`ExeFSReader.decompress_code`, and you should probably use that instead if you are loading the code from an ExeFS.

Exceptions
----------

.. autoexception:: ExeFSError
.. autoexception:: ExeFSFileNotFoundError
.. autoexception:: InvalidExeFSError
.. autoexception:: ExeFSNameError
.. autoexception:: BadOffsetError
.. autoexception:: CodeDecompressionError
