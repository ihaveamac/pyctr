:mod:`nand` - NAND images
=========================

.. py:module:: pyctr.type.nand
    :synopsis: Read and write Nintendo 3DS NAND images

The :mod:`nand` module enables reading and writing of Nintendo 3DS NAND images.

This module is best combined with `pyfatfs <https://github.com/nathanhi/pyfatfs>`_ for interacting with the FAT filesystems inside TWL NAND and CTR NAND. pyfatfs is not a dependency on pyctr so your application must include it manually.

A basic overview of reading and writing to a NAND image is available here: :doc:`example-nand`.

NAND objects
------------

.. autoclass:: NAND

    .. automethod:: open_ctr_partition
    .. automethod:: open_twl_partition
    .. py:method:: open_raw_section(section)

        Opens a raw NCSD section for reading and writing with on-the-fly decryption.

        You should use :class:`NANDSection` to get a specific type of partition. Unless you need to interact with the physical location of partitions, using partition indexes could break for users who have moved them around.

        .. note::

            If you are looking to read from TWL NAND or CTR NAND, you may be looking for :meth:`open_twl_partition`
            or :meth:`open_ctr_partition` instead.

        :param section: The section to open. Numbers 0 to 7 are specific NCSD partitions. Negative numbers are special
            sections defined by PyCTR.
        :type section: Union[NANDSection, int]
        :return: A file-like object.
        :rtype: SubsectionIO

    .. automethod:: open_bonus_partition
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

            Writes to the first 0x1BE (before the TWL MBR) are silently discarded to avoid writing a corrupted NCSD header.

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
