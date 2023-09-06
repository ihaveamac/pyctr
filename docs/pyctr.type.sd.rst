:mod:`sd` - SD card contents
============================

.. py:module:: pyctr.type.sd
    :synopsis: Read and write Nintendo 3DS SD card encrypted digital content

The :mod:`sd` module enables reading and writing of Nintendo 3DS SD card encrypted digital content. This is the "Nintendo 3DS" folder on an SD card and includes application data, save data, and extdata.

.. deprecated:: 0.8.0
    Replaced with :mod:`~pyctr.type.sdfs`.

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

SDFilesystem objects
--------------------

.. py:class:: SDFilesystem(path, *, crypto=None, dev=False, sd_key_file=None, sd_key=None)

    Read and write encrypted SD card contents in the "Nintendo 3DS" directory.

    All methods related to files and directories happen relative to the root of the ID1 folder. Each have an optional ``id1`` parameter to specify a specific ID1 directory. If left unspecified, the value of :attr:`current_id1` is used.

    :param path: Path to the Nintendo 3DS folder.
    :type path: str
    :param crypto: A custom crypto object to be used. Defaults to None, which causes a new one to be created.
    :type crypto: ~pyctr.crypto.engine.CryptoEngine
    :param sd_key_file: Path to a movable.sed file to load the SD KeyY from.
    :type sd_key_file: :term:`path-like object` or :term:`binary file`
    :param sd_key: SD KeyY to use. Has priority over `sd_key_file` if both are specified.
    :type sd_key: bytes
    :raises MissingMovableSedError: If movable.sed is not provided.
    :raises MissingID0Error: If the ID0 could not be found in "Nintendo 3DS".
    :raises MissingID1Error: If there are no ID1 directories inside ID0.

    .. py:method:: open_title(title_id, *, case_insensitive=False, seed=None, load_contents=True, id1=None)

        Open a title's contents for reading.

        In the case where a title's directory has multiple tmd files, the first one returned by :meth:`listdir` is used.

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

    .. py:method:: open(path, mode='rb', *, id1=None)

        Opens a file in the SD filesystem for reading or writing. Unix and Windows style paths are accepted.

        This does not support reading or writing files in the "Nintendo DSiWare" directory, which use a very different encryption method. Attempting will raise :exc:`NotImplementedError`.

        :param path: File path.
        :type path: :term:`path-like object`
        :param mode: Mode to open the file with. Binary mode is always used.
        :type mode: str
        :rtype: ~pyctr.crypto.engine.CTRFileIO

    .. py:method:: listdir(path, id1=None)

        Returns a list of files in the directory.

        :param path: Directory path.
        :type path: :term:`path-like object`
        :rtype: List[str]

    .. py:method:: isfile(path, id1=None)

        Checks if the path points to a file.

        :param path: Path to check.
        :type path: :term:`path-like object`
        :rtype: bool

    .. py:method:: isdir(path, id1=None)

        Checks if the path points to a directory.

        :param path: Path to check.
        :type path: :term:`path-like object`
        :rtype: bool

    .. py:attribute:: id1s
        :type: List[str]

        A list of ID1 directories found in the ID0 directory.

    .. py:attribute:: current_id1
        :type: str

        The ID1 used as the default when none is specified to a method's ``id1`` argument, initially set to the first value in :attr:`id1s`.

        .. note::

            If there is more than one ID1, the default value is whichever happens to be returned by the OS first. This could be different from what is actually used on someone's console.

Exceptions
----------

.. autoexception:: SDFilesystemError
.. autoexception:: MissingMovableSedError
.. autoexception:: MissingID0Error
.. autoexception:: MissingID1Error
.. autoexception:: MissingTitleError
