:mod:`seeddb` - SeedDB management
=================================

.. py:module:: pyctr.crypto.seeddb
    :synopsis: Manage title encryption seeds

The :mod:`seeddb` module handles seeds used for title encryption. This applies to digital games released after early 2015. Seeds were used to enable pre-purchasing and downloading titles before release without providing access to the actual contents before the release date.

When a :class:`~pyctr.crypto.engine.CryptoEngine` object is initialized, by default it will attempt to load a ``seeddb.bin`` using the paths defined in :attr:`seeddb_paths`.

File format
-----------

The SeedDB file consists of a seed count, then each entry has a Title ID and its associated seed.

.. list-table:: seeddb.bin file format
    :header-rows: 1

    * - Offset
      - Size
      - Data
    * - 0x0
      - 0x4
      - Entry count in little endian (C)
    * - 0x4
      - 0xC
      - Padding
    * - 0x10
      - (0x20 * C)
      - Entries

.. list-table:: Entry
    :header-rows: 1

    * - Offset
      - Size
      - Data
    * - 0x0
      - 0x8
      - Title ID in little endian
    * - 0x8
      - 0x10
      - Seed
    * - 0x18
      - 0x8
      - Padding

Functions
---------

.. autofunction:: load_seeddb

.. autofunction:: get_seed

.. autofunction:: add_seed

.. autofunction:: get_all_seeds

.. autofunction:: save_seeddb

Data
----

.. py:data:: seeddb_paths
    :type: Dict[int, bytes]

    The list of paths that :meth:`load_seeddb` will try to load from automatically. By default this is every path in :attr:`pyctr.util.config_dirs` with ``seeddb.bin``. If the environment variable ``SEEDDB_PATH`` is set, its value is put at the beginning of the list.
