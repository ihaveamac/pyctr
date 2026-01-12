# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from pathlib import Path
from struct import Struct
from sys import getdefaultencoding
from typing import TYPE_CHECKING
from warnings import filterwarnings, simplefilter

from Cryptodome.Cipher import AES
from requests import Session
from urllib3.exceptions import InsecureRequestWarning
from fs.appfs import UserCacheFS

from pyctr.type.smdh import AppTitle, SMDHRegionLockout

if TYPE_CHECKING:
    from typing import Union, Optional

# The SSL certs used here are old and requests/urllib3 really don't like it.
# The warning is "Unverified HTTPS request is being made to host 'idbe-ctr.cdn.nintendo.net'."
# But using Nintendo's SSL certs makes it an error instead on newer versions of requests/urllib3.
# So instead we just ignore it. It's fine in this particular case. Probably.
# Also using pycurl was too annoying, especially on Windows.
filterwarnings('ignore', r'.*idbe-ctr\.cdn\.nintendo\.net.*', InsecureRequestWarning)

try:
    idbe_cache_fs = UserCacheFS('pyctr', 'ihaveahax')
except Exception as e:
    idbe_cache_fs = None

_session = Session()
_session.verify = False
_session.headers.update({'User-Agent': '3ds'})  # i need to get the real user-agent

IDBE_SIZE = 0x36D0
IDBE_SIZE_ENCRYPTED = IDBE_SIZE + 2  # includes key index and an unused value

IDBE_URL = 'https://idbe-ctr.cdn.nintendo.net/icondata/10/%016X.idbe'
IDBE_URL_VERSIONED = 'https://idbe-ctr.cdn.nintendo.net/icondata/10/%016X-%d.idbe'

IDBE_IV = bytes.fromhex('A46987AE47D82BB4FA8ABC0450285FA4')

IDBE_KEYS = (
    bytes.fromhex("4AB9A40E146975A84BB1B4F3ECEFC47B"),
    bytes.fromhex("90A0BB1E0E864AE87D13A6A03D28C9B8"),
    bytes.fromhex("FFBB57C14E98EC6975B384FCF40786B5"),
    bytes.fromhex("80923799B41F36A6A75FB8B48C95F66F"),
)

# unknown values are preserved so the IDBE struct can be rebuilt
idbe_decrypted_struct = Struct(
    '<'
    '32s'    # SHA-256 hash
    'Q'      # Title ID
    '8s'    # unknown
    'i'      # region lockout
    '28s'    # unknown
    '512s'   # title structs
    '1152s'  # 24x24 icon
    '4608s'  # 48x48 icon
)

if idbe_cache_fs:
    print('Cache path:', idbe_cache_fs.getospath('/'))


class IDBE:
    def __init__(self) -> None:
        pass

    @classmethod
    def get(cls, title_id: 'Union[str, int]', version: 'Optional[int]' = None, /, *, cache: bool = True):
        """
        Get an icon from IDBE.

        :param title_id: Title ID of the application.
        :param version: Icon version. Leave unset to get the latest.
        :param cache: Store and retrieve the icon from the local cache.
        :return: IDBE object with the parsed data.
        """
        if isinstance(title_id, str):
            title_id = int(title_id, 16)
        if version:
            url = IDBE_URL_VERSIONED % (title_id, version)
            idbe_cache_file = ('%016x-%d.idbe' % (title_id, version))
        else:
            url = IDBE_URL % (title_id,)
            idbe_cache_file = ('%016x.idbe' % (title_id,))

        print(url)

        if idbe_cache_fs and cache and idbe_cache_fs.isfile(idbe_cache_file):
            with idbe_cache_fs.open(idbe_cache_file, 'rb') as f:
                data_dec = f.read(IDBE_SIZE)
                return data_dec

        with _session.get(url) as r:
            r.raise_for_status()
            data: bytes = r.content

        key = IDBE_KEYS[data[1]]
        cipher = AES.new(key, AES.MODE_CBC, IDBE_IV)
        data_dec = cipher.decrypt(data[2:])

        if idbe_cache_fs and cache:
            idbe_cache_fs.writebytes(idbe_cache_file, data_dec)
