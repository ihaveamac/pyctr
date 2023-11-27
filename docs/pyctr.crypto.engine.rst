:mod:`engine` - AES engine tools
================================

.. py:module:: pyctr.crypto.engine
    :synopsis: Perform cryptographic operations operations with Nintendo 3DS data

The :mod:`engine` module provides tools to perform cryptographic operations on Nintendo 3DS data, including emulating keyslots and the key scrambler.

.. warning::

    This page is incomplete.

AES engine
----------

The 3DS uses keyslots in an attempt to obscure the encryption keys used. Each slot consists of X, Y, and normal keys.

Often, one slot contains a fixed key (often X), while the other is a key unique to something such as a game or console (often Y). When key Y is set, both keys are put into a key scrambler, and the result is stored as a normal key. The AES engine would then use the result for encryption. A normal key can also be set directly.

The AES engine only has keyslots 0x0 to 0x3F (0 to 63). Keyslots 0x0 to 0x3 are for DSi-mode software, and use the DSi key scrambler. This module uses keyslots above 0x3F for internal use.

CryptoEngine objects
--------------------

.. py:class:: CryptoEngine(boot9=None, dev=False, setup_b9_keys=True)

    Emulates the AES engine, including keyslots and the key scrambler.

    :param boot9: Path to a dump of the protected region of the ARM9 BootROM. Defaults to None, which causes it to search a predefined list of paths.
    :type boot9: FilePathOrObject
    :param dev: Use devunit keys.
    :type dev: bool
    :param setup_b9_keys: Automatically load keys from boot9. This calls :meth:`setup_boot9_keys`.
    :type setup_b9_keys: bool

    .. py:method:: create_cbc_cipher(keyslot, iv)

        Create an AES-CBC cipher.

        :param keyslot: Keyslot to use.
        :type keyslot: Keyslot
        :param iv: Initialization vector.
        :type iv: bytes
        :return: An AES-CBC cipher object.
        :rtype: CbcMode

    .. py:method:: create_ctr_cipher(keyslot, ctr)

        Create an AES-CTR cipher.

        :param keyslot: Keyslot to use.
        :type keyslot: Keyslot
        :param ctr: Counter to start with.
        :type ctr: int
        :return: An AES-CTR cipher object.
        :rtype: CtrMode | _TWLCryptoWrapper

    .. py:method:: create_ecb_cipher(keyslot)

        Create an AES-ECB cipher.

        :param keyslot: Keyslot to use.
        :type keyslot: Keyslot
        :return: An AES-ECB cipher object.
        :rtype: EcbMode

    .. py:method:: create_cmac_object(keyslot)

        Create a CMAC object.

        :param keyslot: Keyslot to use.
        :type keyslot: Keyslot
        :return: A CMAC object.
        :rtype: CMAC

    .. py:method:: create_ctr_io(keyslot, fh, ctr, closefd=False)

        Create an AES-CTR read-write file object with the given keyslot.

        :param keyslot: Keyslot to use.
        :type keyslot: Keyslot
        :param fh: File-like object to wrap.
        :type fh: BinaryIO
        :param ctr: Counter to start with.
        :type ctr: int
        :param closefd: Close underlying file object when closed.
        :type closefd: bool
        :return: A file-like object that does decryption and encryption on the fly.
        :rtype: CTRFileIO

    .. py:method:: create_cbc_io(keyslot, fh, iv, closefd=False)

        Create an AES-CBC read-write file object with the given keyslot.

        :param keyslot: Keyslot to use.
        :type keyslot: Keyslot
        :param fh: File-like object to wrap.
        :type fh: BinaryIO
        :param iv: Initialization vector.
        :type iv: bytes
        :param closefd: Close underlying file object when closed.
        :type closefd: bool
        :return: A file-like object that does decryption and encryption on the fly.
        :rtype: CBCFileIO

    .. py:method:: set_keyslot(xy, keyslot, key, *, update_normal_key=True)

        Sets a keyslot.

        :param xy: X or Y.
        :type xy: Literal['x', 'y']
        :param keyslot: Keyslot to set.
        :type keyslot: Keyslot
        :param key: Key to set it to. If provided as an integer, it is converted to little- or big-endian depending on if the keyslot is <=0x03.
        :type key: bytes | int
        :param update_normal_key: Update the normal key based on the value of X and Y.
        :type update_normal_key: bool

    .. py:method:: set_normal_key(keyslot, key)

        Set a keyslot's normal key.

        :param keyslot: Keyslot to set.
        :type keyslot: Keyslot
        :param key: Key to set it to.
        :type key: bytes

    .. py:method:: update_normal_keys()

        Refresh normal keys. This is only required if :meth:`set_keyslot` was called with `update_normal_key=False`.
