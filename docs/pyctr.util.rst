:mod:`util` - Utility functions
===============================

.. module:: pyctr.util
    :synopsis: Utility functions for PyCTR

The :mod:`util` module contains extra useful functions.

.. autofunction:: readle
.. autofunction:: readbe
.. autofunction:: roundup

.. py:data:: windows
    :type: bool

    If the current platform is Windows.

.. py:data:: macos
    :type: bool

    If the current platform is macOS.

.. py:data:: config_dirs
    :type: List[str]

    Data directories that should contain the ARM9 bootROM (boot9.bin), SeedDB (seeddb.bin), and other files.

    This includes ``~/.3ds`` and ``~/3ds``. On Windows this also includes ``%APPDATA%\3ds``. On macOS this also includes ``~/Library/Application Support/3ds``.
