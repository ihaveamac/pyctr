.. pyctr documentation master file, created by
   sphinx-quickstart on Wed Mar 16 02:56:34 2022.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to pyctr's documentation!
=================================

PyCTR is a Python library to interact with Nintendo 3DS files.

It can read data from different kinds of files:

* CDN contents - :mod:`pyctr.type.cdn`
* Game card dumps (CTR Cart Image/CCI) - :mod:`pyctr.type.cci`
* CIA files (CTR Importable Archive) - :mod:`pyctr.type.cia`
* ExeFS containers - :mod:`pyctr.type.exefs`
* RomFS containers - :mod:`pyctr.type.romfs`
* NCCH containers - :mod:`pyctr.type.ncch`
* NAND backups - :mod:`pyctr.type.nand`
* SD card files inside "Nintendo 3DS" - :mod:`pyctr.type.sd`
* SD card titles - :mod:`pyctr.type.sdtitle`
* SMDH icons - :mod:`pyctr.type.smdh`
* Title Metadata files (TMD) - :mod:`pyctr.type.tmd`

It can emulate cryptography features of the 3DS:

* AES key engine and key scrambler - :mod:`pyctr.crypto.engine`
* Seed database (SeedDB) - :mod:`pyctr.crypto.seeddb`

Install
=======

PyCTR requires Python 3.8 or later.

It can be installed with ``pip``:

.. code-block:: console

    $ pip install pyctr

.. toctree::
   :maxdepth: 1
   :caption: Getting started

   example-cia
   example-nand

.. toctree::
   :maxdepth: 1
   :caption: App containers

   pyctr.type.cdn
   pyctr.type.cia
   pyctr.type.cci
   pyctr.type.ncch
   pyctr.type.sdtitle

.. toctree::
   :maxdepth: 1
   :caption: App data

   pyctr.type.exefs
   pyctr.type.romfs

.. toctree::
   :maxdepth: 1
   :caption: App metadata

   pyctr.type.smdh
   pyctr.type.tmd

.. toctree::
   :maxdepth: 1
   :caption: Console data

   pyctr.type.nand
   pyctr.type.sdfs
   pyctr.type.sd

.. toctree::
   :maxdepth: 1
   :caption: Encryption

   pyctr.crypto.engine
   pyctr.crypto.seeddb

.. toctree::
   :maxdepth: 1
   :caption: Extras

   pyctr.util
   pyctr.fileio


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
