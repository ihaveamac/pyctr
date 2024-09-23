:mod:`smdh` - SMDH icons
========================

.. py:module:: pyctr.type.smdh
    :synopsis: Parse SMDH icon data

The :mod:`smdh` module enables reading SMDH icons, including converting the graphical icon data to a standard format, reading application titles, and settings.

This module can use Pillow if it is installed, to provide icon data as :class:`PIL.Image.Image` objects.

SMDH objects
------------

.. autoclass:: SMDH
    :members:
    :undoc-members:
    :show-inheritance:

Exceptions
----------

.. autoexception:: SMDHError
.. autoexception:: InvalidSMDHError
