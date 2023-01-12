.. pyctr documentation master file, created by
   sphinx-quickstart on Wed Mar 16 02:56:34 2022.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to pyctr's documentation!
=================================

PyCTR is a Python library to interact with Nintendo 3DS files.

It can read data from different kinds of files:

* CDN contents - :py:mod:`pyctr.type.cdn`
* Game card dumps (CTR Cart Image/CCI) - :py:mod:`pyctr.type.cci`
* CIA files (CTR Importable Archive) - :py:mod:`pyctr.type.cia`
* ExeFS containers - :py:mod:`pyctr.type.exefs`
* RomFS containers - :py:mod:`pyctr.type.romfs`
* NCCH containers - :py:mod:`pyctr.type.ncch`
* NAND backups - :py:mod:`pyctr.type.nand`
* SD card files inside "Nintendo 3DS" - :py:mod:`pyctr.type.sd`
* SD card titles - :py:mod:`pyctr.type.sdtitle`
* SMDH icons - :py:mod:`pyctr.type.smdh`
* Title Metadata files (TMD) - :py:mod:`pyctr.type.tmd`

It can emulate cryptography features of the 3DS:

* AES key engine and key scrambler - :py:mod:`pyctr.crypto.engine`
* Seed database (SeedDB) - :py:mod:`pyctr.crypto.seeddb`

Install
=======

PyCTR requires Python 3.6.1 or later.

It can be installed with ``pip``:

.. code-block:: console

    $ pip install pyctr

.. toctree::
   :maxdepth: 2
   :caption: Getting started

   example-cia

.. toctree::
   :maxdepth: 5
   :caption: Contents:

   pyctr


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
