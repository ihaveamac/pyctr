# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from importlib import resources
from json import load
from collections import namedtuple

__author__ = 'ihaveamac'
__copyright__ = 'Copyright (c) 2017-2023 Ian Burgwin'
__license__ = 'MIT'

#_package_files = resources.files()
#_version_file = _package_files / 'version.json'
#_version_data = loads(_version_file.read_text('utf-8'))
with resources.open_text(__package__, 'version.json', encoding='utf-8') as f:
    _version_data = load(f)
_VersionInfo = namedtuple('VersionInfo', 'major minor micro releaselevel serial')
version_info = _VersionInfo(**_version_data['tuple'])
__version__ = _version_data['version']
