:mod:`sdfs` - SD card filesystem
================================

.. py:module:: pyctr.type.sdfs
    :synopsis: Read and write Nintendo 3DS SD card encrypted digital content

The :mod:`sd` module enables reading and writing of Nintendo 3DS SD card encrypted digital content. This is the "Nintendo 3DS" folder on an SD card and includes application data, save data, and extdata.

Directory hierarchy
-------------------

* Nintendo 3DS

  * <id0>

    * <id1>

      * backup

      * dbs

      * extdata

      * title

      * Nintendo DSiWare

Getting started
---------------

There are two or three steps to get access to the filesystem inside id1. First you create an :class:`SDRoot` object pointing at a "Nintendo 3DS" folder. Then, if you wish, you can select an id1 directory to use. Then use :meth:`~SDRoot.open_id1` to open the filesystem it and receive an :class:`SDFS` object.

.. code-block:: python

    from pyctr.type.sdfs import SDRoot, SDFS

    root = SDRoot('/Volumes/GM9SD/Nintendo 3DS',
                  sd_key_file='movable.sed')
    # at this point check root.id1s if you wish, and then pass it to open_id1
    # or don't, and it will select the first one it finds
    fs = root.open_id1()
    with fs.open('/dbs/title.db') as f:
        f.read()

You can also use the :class:`SDRoot` to open titles. It also accepts an id1 or will use the first one by default.

.. code-block:: python

    title = sd.open_title('0004000000169800')
    with title.contents[0].romfs.open('/file.bin') as f:
        f.read()

SDRoot objects
--------------

.. py:class:: SDRoot(path, *, crypto=None, dev=False, sd_key_file=None, sd_key=None)

    Opens an ID0 folder inside a "Nintendo 3DS" folder.

    :param path: Path to the Nintendo 3DS folder.
    :param crypto: A custom :class:`crypto.CryptoEngine` object to be used. Defaults to None, which causes a new one to
        be created.
    :param dev: Use devunit keys.
    :param sd_key_file: Path to a movable.sed file to load the SD KeyY from.
    :param sd_key: SD KeyY to use. Has priority over `sd_key_file` if both are specified.

    .. py:method:: open_id1(id1=None)

        Opens the filesystem inside an ID1 directory.

        if no ID1 is specified, the first one in :attr:`id1s` is used.

        :param id1: ID1 directory to use.
        :type id1: Optional[str]
        :return: SD filesystem.
        :rtype: SDFS
        :raises fs.errors.ResourceNotFound: If the ID1 directory doesn't exist.

    .. py:method:: open_title(title_id, *, case_insensitive=False, seed=None, load_contents=True)

        Open a title's contents for reading.

        In the case where a title's directory has multiple tmd files, the one with the smallest number in the filename is used.

        :param title_id: Title ID to open.
        :type title_id: str
        :param case_insensitive: Use case-insensitive paths for the RomFS of each NCCH container.
        :type case_insensitive: bool
        :param seed: Seed to use. This is a quick way to add a seed using :func:`~.seeddb.add_seed`.
        :type seed: bytes
        :param load_contents: Load each partition with :class:`~.NCCHReader`.
        :type load_contents: bool
        :rtype: ~pyctr.type.sdtitle.SDTitleReader
        :raises MissingTitleError: If the title could not be found.

SDFS objects
------------

These are created by :class:`SDRoot` and usually shouldn't be created manually.

These inherit :class:`fs.base.FS` and so generally the same methods work.

.. py:class:: SDFS(parent_fs, path, *, crypto)

    Enables access to an SD card filesystem inside Nintendo 3DS/id0/id1.

    Currently, files inside the "Nintendo 3DS" directory cannot be read.

    :param parent_fs: The filesystem containing the contents of "Nintendo 3DS".
    :type parent_fs: ~fs.base.FS
    :param path: The path to the id1 folder.
    :type path: str
    :param crypto: The :class:`~pyctr.crypto.engine.CryptoEngine` object to be used.
    :type crypto: ~pyctr.crypto.engine.CryptoEngine
