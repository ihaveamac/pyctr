Example: Read and write NAND partitions
=======================================

In this example we will take a dumped Nintendo 3DS NAND image and extract data from the partitions.

`Use GodMode9 to dump the NAND and essential files from your console. <https://wiki.hacks.guide/wiki/3DS:GodMode9/Usage#Creating_a_NAND_Backup>`_ No examples files are provided.

.. note::
    This is only an introduction to the NAND class assuming a valid NAND backup is being used. There are plenty of ways for this to go wrong in practice, from a corrupt TWL MBR, to no embedded essentials backup or an outdated one (such as lacking ``hwcal0`` and ``hwcal1`` or containing un-updated files like ``movable``).

    (soon) The full :class:`~.NAND` module documentation helps you to figure out how to handle these cases.

First we need to import :class:`~.NAND`, and use it to open our NAND backup. In this case we will assume it has the GodMode9 essentials backup embedded.

When opening a NAND backup file without any additional arguments, it is read-only by default.

.. code-block:: python

    >>> from pyctr.type.nand import NAND
    >>> nand = NAND('nand.bin')

With this we now immediately have access to decrypted versions of every NCSD partition and the GodMode9 bonus partition if it exists. We can also access the essentials backup with the :attr:`essential <pyctr.type.nand.NAND.essential>` attribute, an :class:`~.ExeFSReader` object.

Most of the time when interacting with a NAND backup, we'll want to access CTR NAND. There is a convenience function that will immediately open the CTR NAND FAT32 partition and enable access to the filesystem, :meth:`~pyctr.type.nand.NAND.open_ctr_fat`. This returns a :external+pyfatfs:class:`PyFatBytesIOFS <pyfatfs.PyFatFS.PyFatBytesIOFS>`, provided by `pyfatfs <https://github.com/nathanhi/pyfatfs>`_.

.. code-block:: python

    >>> ctrfat = nand.open_ctr_fat()

With that let's list the files and open one.

.. code-block:: python

    >>> ctrfat.listdir('/')
    ['data', 'ro', 'rw', 'ticket', 'title', 'tmp', 'fixdata', 'dbs', 'private', '__journal.nn_']
    >>> ctrfat.listdir('/private')
    ['movable.sed']
    >>> msed_file = ctrfat.open('/private/movable.sed', 'rb')
    >>> msed_file.seek(0x110)
    >>> msed = msed_file.read(0x10)
    >>> print('movable.sed key:', msed.hex())
    movable.sed key: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

Once done, let's remember to close all the files properly.

.. code-block:: python

    >>> msed_file.close()
    >>> ctrnand.close()
    >>> nand.close()

Writing
-------

We've done enough reading. Let's write some files to the NAND now.

To do this, the second argument for :class:`~.NAND` should be given ``'rb+'``.

.. code-block:: python

    >>> from pyctr.type.nand import NAND, NANDSection
    >>> from pyfatfs.PyFatFS import PyFatBytesIOFS
    >>> nand = NAND('nand.bin', 'rb+')
    >>> ctrfat = nand.open_ctr_fat()

With the NAND in read-write mode we can open files for writing now.

.. code-block:: python

    >>> myfile = ctrfat.open('/myfile.txt', 'wb')
    >>> myfile.write(b'my contents')
    >>> myfile.close()

Context managers
----------------

Files can all be opened using context managers as well.

.. code-block:: python

    with NAND('nand.bin') as nand:
        with nand.open_ctr_fat() as ctrfat:
            with ctrfat.open('/myfile.txt', 'rb') as f:
                print(f.read())

Next steps
----------

Now that you know the basics of reading and writing to a NAND backup, you may want to check out these methods:

* :meth:`~pyctr.type.nand.NAND.open_ctr_partition` - opens the raw CTR NAND partition
* :meth:`~pyctr.type.nand.NAND.open_twl_partition` - opens a raw TWL NAND partition
* :meth:`~pyctr.type.nand.NAND.open_bonus_partition` - opens the raw bonus partition created by GodMode9
* :meth:`~pyctr.type.nand.NAND.open_ctr_fat` - opens the FAT16 filesystem in the CTR NAND partition
* :meth:`~pyctr.type.nand.NAND.open_twl_fat` - opens the FAT12/FAT16 filesystem in a TWL NAND partition
* :meth:`~pyctr.type.nand.NAND.open_bonus_fat` - opens the FAT32 filesystem in the GodMode9 bonus partition
* :meth:`~pyctr.type.nand.NAND.open_raw_section` - opens a raw NCSD section
* :meth:`~pyctr.type.nand.NAND.raise_if_ctr_failed` - raise an error if CTR partitions are inaccessible
* :meth:`~pyctr.type.nand.NAND.raise_if_twl_failed` - raise an error if TWL partitions are inaccessible
