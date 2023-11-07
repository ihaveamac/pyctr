:mod:`nand` - NAND images
=========================

.. py:module:: pyctr.type.nand
    :synopsis: Read and write Nintendo 3DS NAND images

The :mod:`nand` module enables reading and writing of Nintendo 3DS NAND images.

A basic overview of reading and writing to a NAND image is available here: :doc:`example-nand`.

Getting started
---------------

Here's a quick example to get inside CTRNAND and read files from within it using :mod:`~pyfatfs.PyFatBytesIOFS`:

.. code-block:: python

    from pyctr.type.nand import NAND
    from pyfatfs.PyFatFS import PyFatBytesIOFS

    with NAND('nand.bin') as nand:
        with PyFatBytesIOFS(fp=nand.open_ctr_partition()) as ctrfat:
            with ctrfat.open('/private/movable.sed', 'rb') as msed:
                msed.read()

A second example trying to load SecureInfo. This one is tricky because some consoles use ``SecureInfo_A`` and some use ``SecureInfo_B``, so we have to try both.

.. code-block:: python

    from pyctr.type.nand import NAND
    from pyfatfs.PyFatFS import PyFatBytesIOFS
    from fs.errors import ResourceNotFound

    with NAND('nand.bin') as nand:
        with PyFatBytesIOFS(fp=nand.open_ctr_partition()) as ctrfat:
            for l in 'AB':
                path = '/rw/sys/SecureInfo_' + l
                if ctrfat.exists(path):
                    with ctrfat.open(path, 'rb') as f:
                        f.read()
                        break

Required files
--------------

In most cases users will have a NAND backup with an essentials backup embedded. However there are plenty of cases where this may not occur, so you may need to provide support files in other ways.

The only hard requirement is an OTP. This is found in the essentials backup, but otherwise can be provided as a file, file-like object, and a bytestring.

NAND CID is also useful to have but is not required for most consoles. This also is loaded from the essentials backup if found, otherwise it can be provided like OTP. If it's not found anywhere, PyCTR will attempt to generate the Counter for both CTR and TWL. The Counter for TWL will not be generated if the TWL MBR is corrupt.

In either case the load priority is first file, then bytestring, then essentials backup.

An external ``essential.exefs`` file must manually be loaded with :class:`~.ExeFSReader` and then the individual ``otp`` and ``nand_cid`` read and provided to the :mod:`NAND` initializer.

Dealing with corruption
-----------------------

There are cases where the NAND is corrupt but you still want to read it.

One of the most common kinds of corruption is an invalid TWL MBR. This happens if the NCSD header is replaced with one of another console. This applies mostly to very old pre-sighax NAND backups. If the TWL MBR cannot be decrypted and parsed, but a NAND CID was loaded, PyCTR will use the default partition information. Otherwise, TWL information will be inaccessible.

NAND objects
------------

.. autoclass:: NAND

    .. automethod:: open_ctr_partition
    .. automethod:: open_ctr_fat
    .. automethod:: open_twl_partition
    .. automethod:: open_twl_fat
    .. py:method:: open_raw_section(section)

        Opens a raw NCSD section for reading and writing with on-the-fly decryption.

        You should use :class:`NANDSection` to get a specific type of partition. Unless you need to interact with the physical location of partitions, using partition indexes could break for users who have moved them around.

        .. note::

            If you are looking to read from TWL NAND or CTR NAND, you may be looking for :meth:`open_twl_partition`
            or :meth:`open_ctr_partition` instead to open the raw MBR partition. This will return NCSD partitions,
            which for TWL NAND and CTR NAND, include the MBR.

        :param section: The section to open. Numbers 0 to 7 are specific NCSD partitions. Negative numbers are special
            sections defined by PyCTR.
        :type section: Union[NANDSection, int]
        :return: A file-like object.
        :rtype: SubsectionIO

    .. automethod:: open_bonus_partition
    .. automethod:: open_bonus_fat
    .. automethod:: raise_if_ctr_failed
    .. automethod:: raise_if_twl_failed

    .. py:attribute:: essential

        The embedded GodMode9 essentials backup.

        This usually contains these files:

        * ``frndseed``
        * ``hwcal0``
        * ``hwcal1``
        * ``movable``
        * ``nand_cid``
        * ``nand_hdr``
        * ``otp``
        * ``secinfo``

        :type: ExeFSReader

    .. py:attribute:: ctr_partitions

        The list of partitions in the CTR MBR. Always only one in practice, referred to as CTR NAND.

        :type: List[Tuple[int, int]]

    .. py:attribute:: twl_partitions

        The list of partitions in the TWL MBR. First one is TWL NAND and second is TWL Photo.

        :type: List[Tuple[int, int]]

    .. automethod:: close

NAND sections
-------------

.. py:class:: NANDSection

    This defines the location of partitions in a NAND.

    All the enums here are negative numbers to refer to different types of partitions rather than physical locations when used with :meth:`NAND.open_raw_section`, because while 99% of users will never alter the partitions, it is still possible to do so and this module will handle those use cases.

    .. autoattribute:: Header
    .. autoattribute:: TWLMBR
    .. autoattribute:: TWLNAND

        .. note::

            Don't write to the first 0x1BE, this is where the NCSD header is on the raw NAND. Future versions of pyctr may silently discard writes to this region.

            If writing to the TWL MBR region (0x1BE-0x200), the NCSD header signature may be invalidated. Use the sighax signature to keep a "valid" header. Also keep a backup of the original NCSD header (this may already be in the essentials backup).

    .. autoattribute:: AGBSAVE
    .. autoattribute:: FIRM0
    .. autoattribute:: FIRM1
    .. autoattribute:: CTRNAND

    Special sections
    ~~~~~~~~~~~~~~~~

    These are not actual sections of the NAND/NCSD but are included for convenience.

    .. autoattribute:: Sector0x96

        .. note::

            Reading this decrypted with :meth:`~NAND.open_raw_section` is not yet supported. Decrypt it manually if you need access to it.

    .. autoattribute:: GM9BonusVolume
    .. autoattribute:: MinSize

Exceptions
----------

.. autoexception:: NANDError
.. autoexception:: InvalidNANDError
.. autoexception:: MissingOTPError

Custom NCSD interaction
-----------------------

These are for those who want to manually interact with the NCSD information.

.. autoclass:: NANDNCSDHeader

    This contains all the information in the NCSD header. This is also used for virtual sections in PyCTR.

    .. autoattribute:: signature
    .. py:attribute:: image_size
        :type: int

        Claimed image size. This does not actually line up with the raw image size in sectors, but is useful to determine Old 3DS vs New 3DS.

    .. autoattribute:: actual_image_size
    .. py:attribute:: partition_table
        :type: Dict[Union[int, NANDSection], NCSDPartitionInfo]

        Partition information. :class:`NANDSection` keys (negative ints) are for partition and section types, while positive int keys are for physical locations. This means that, for example, :attr:`NANDSection.TWLMBR` and ``0`` contain the same partition info.

    .. autoattribute:: twl_mbr_encrypted
    .. autoattribute:: unknown

    .. py:classmethod:: load(fp)

        Load a NAND header from a file-like object. This will also seek to :attr:`actual_image_size` to determine if there is a GodMode9 bonus drive.

        :param fp: The file-like object to read from. Must be seekable.
        :type fp: typing.BinaryIO

    .. automethod:: from_bytes

.. py:class:: NCSDPartitionInfo

    Information for a single partition.

    .. py:attribute:: fs_type
        :type: Union[PartitionFSType, int]

        Type of filesystem.

    .. py:attribute:: encryption_type
        :type: Union[PartitionEncryptionType, int]

        Type of encryption used for the partition.

    .. py:attribute:: offset
        :type: int

        Offset of the partition in bytes.

    .. py:attribute:: size
        :type: int

        Size of the partition in bytes.

Enums
~~~~~

.. autoclass:: PartitionFSType
    :members:
    :undoc-members:

.. autoclass:: PartitionEncryptionType
    :members:
    :undoc-members:
