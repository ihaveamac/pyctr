# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from io import BytesIO
from os.path import dirname, join, realpath

from hashlib import sha256

import pytest

from pyctr.type import romfs
from fs.info import Info
from fs.enums import ResourceType


def get_file_path(*parts: str):
    return join(dirname(realpath(__file__)), *parts)


def get_romfs_path():
    return get_file_path('fixtures', 'romfs.bin')


def load_romfs_into_bytesio():
    with open(get_romfs_path(), 'rb') as raw:
        mem = BytesIO(raw.read())
    return mem


def open_romfs(case_insensitive=False, closefd=None, open_compatibility_mode=True):
    return romfs.RomFSReader(get_romfs_path(),
                             case_insensitive=case_insensitive,
                             closefd=closefd,
                             open_compatibility_mode=open_compatibility_mode)


def test_no_file():
    with pytest.raises(FileNotFoundError):
        romfs.RomFSReader('nope.bin')


def test_read_file():
    with open_romfs() as reader:
        with reader.open('/utf16.txt', 'rb') as f:
            data = f.read()
            filehash = sha256(data)
            assert filehash.hexdigest() == '1ac2ddff4940809ea36a3e82e9f28bc2f5733275c1baa6ce9f5e434b3a7eab5b'


def test_read_text_file():
    with open_romfs() as reader:
        with reader.open('/utf16.txt', encoding='utf-16') as f:
            text = f.read()
            assert text == 'UTF-16 text!\nFor testing!'


def test_read_past_file():
    with open_romfs() as reader:
        with reader.open('/utf16.txt', 'rb') as f:
            # This file is 0x34 (52) bytes, this should hopefully not read more than that.
            data = f.read(0x40)
            assert len(data) == 0x34


def test_get_file_info():
    with open_romfs() as reader:
        info = reader.getinfo('/utf16.txt')
        assert isinstance(info, Info)
        assert info.name == 'utf16.txt'
        assert info.type == ResourceType.file
        assert info.size == 52
        assert info.get('rawfs', 'offset') == 0


def test_get_dir_info():
    with open_romfs() as reader:
        info = reader.getinfo('/')
        assert isinstance(info, Info)
        assert info.name == 'ROOT'
        assert info.type == ResourceType.directory


def test_listdir():
    with open_romfs() as reader:
        contents = reader.listdir('./')
        assert contents == ['testdir', 'utf16.txt', 'utf8.txt']


def test_get_nonroot_dir_info():
    with open_romfs() as reader:
        info = reader.getinfo('/testdir')
        assert isinstance(info, Info)
        assert info.name == 'testdir'
        assert info.type == ResourceType.directory


def test_nonroot_listdir():
    with open_romfs() as reader:
        contents = reader.listdir('/testdir')
        assert contents == ['emptyfile.bin']


def test_missing_file():
    with open_romfs() as reader:
        with pytest.raises(romfs.RomFSFileNotFoundError):
            reader.open('/nonexistant.bin')


def test_get_missing_file_info():
    with open_romfs() as reader:
        with pytest.raises(romfs.RomFSFileNotFoundError):
            reader.getinfo('/nonexistant.bin')


def test_open_on_directory():
    with open_romfs() as reader:
        with pytest.raises(romfs.RomFSIsADirectoryError):
            reader.open('/testdir')


def test_case_insensitive():
    with open_romfs(case_insensitive=True) as reader:
        assert reader.getinfo('/TESTDIR/EMPTYFILE.BIN').name == 'emptyfile.bin'


def test_closefd_false():
    reader = open_romfs(closefd=False)
    assert reader._file.closed is False
    reader.close()
    assert reader.closed is True
    assert reader._file.closed is False


def test_no_open_compatibility_mode():
    with open_romfs(open_compatibility_mode=False) as reader:
        # fs defaults to utf-8 so let's see if this opens and reads at that successfully
        with reader.open('/utf8.txt') as f:
            data = f.read()
            assert data == 'UTF-8 test:\nニンテンドー3DS'


def test_deprecated_read_file():
    with open_romfs() as reader:
        with pytest.warns(DeprecationWarning):
            with reader.open('/utf16.txt') as f:
                data = f.read()
                filehash = sha256(data)
                assert filehash.hexdigest() == '1ac2ddff4940809ea36a3e82e9f28bc2f5733275c1baa6ce9f5e434b3a7eab5b'


def test_deprecated_read_past_file():
    with open_romfs() as reader:
        with pytest.warns(DeprecationWarning):
            with reader.open('/utf16.txt') as f:
                # This file is 0x34 (52) bytes, this should hopefully not read more than that.
                data = f.read(0x40)
                assert len(data) == 0x34


def test_deprecated_get_file_info():
    with open_romfs() as reader:
        with pytest.warns(DeprecationWarning):
            info = reader.get_info_from_path('/utf16.txt')
            assert isinstance(info, romfs.RomFSFileEntry)
            assert info.name == 'utf16.txt'
            assert info.type == 'file'
            assert info.offset == 0
            assert info.size == 52


def test_deprecated_get_dir_info():
    with open_romfs() as reader:
        with pytest.warns(DeprecationWarning):
            info = reader.get_info_from_path('/')
            assert isinstance(info, romfs.RomFSDirectoryEntry)
            assert info.name == 'ROOT'
            assert info.type == 'dir'
            assert info.contents == ('testdir', 'utf16.txt', 'utf8.txt')


def test_deprecated_get_nonroot_dir_info():
    with open_romfs() as reader:
        with pytest.warns(DeprecationWarning):
            info = reader.get_info_from_path('/testdir')
            assert isinstance(info, romfs.RomFSDirectoryEntry)
            assert info.name == 'testdir'
            assert info.type == 'dir'
            assert info.contents == ('emptyfile.bin',)


def test_deprecated_get_missing_file_info():
    with open_romfs() as reader:
        with pytest.warns(DeprecationWarning), pytest.raises(romfs.RomFSFileNotFoundError):
            reader.get_info_from_path('/nonexistant.bin')


romfs_corrupt_params = (
    (0x4, b'ABCD', romfs.InvalidIVFCError, 'IVFC magic number is invalid (0X44434241 instead of 0X10000)'),
    (0x1000, b'FFFF', romfs.InvalidRomFSHeaderError, 'Length in RomFS Lv3 header is not 0x28'),
    (0x1004, b'\0\0\0\0', romfs.InvalidRomFSHeaderError, 'Directory Hash offset is before the end of the Lv3 header'),
    (0x1008, b'\xff\0\0\0', romfs.InvalidRomFSHeaderError,
     'Directory Metadata offset is before the end of the Directory Hash region'),
    (0x100C, b'\0\0\0\0', romfs.InvalidRomFSHeaderError,
     'Directory Metadata offset is before the end of the Directory Hash region'),
    (0x1010, b'\xff\0\0\0', romfs.InvalidRomFSHeaderError,
     'File Hash offset is before the end of the Directory Metadata region'),
    (0x1014, b'\0\0\0\0', romfs.InvalidRomFSHeaderError,
     'File Hash offset is before the end of the Directory Metadata region'),
    (0x1018, b'\xff\0\0\0', romfs.InvalidRomFSHeaderError,
     'File Metadata offset is before the end of the File Hash region'),
    (0x101C, b'\0\0\0\0', romfs.InvalidRomFSHeaderError,
     'File Metadata offset is before the end of the File Hash region'),
    (0x1020, b'\xff\0\0\0', romfs.InvalidRomFSHeaderError,
     'File Data offset is before the end of the File Metadata region'),
    (0x1024, b'\0\0\0\0', romfs.InvalidRomFSHeaderError,
     'File Data offset is before the end of the File Metadata region'),
)


@pytest.mark.parametrize('seek,data,exc,excstring', romfs_corrupt_params)
def test_corrupt_romfs_file(seek, data, exc, excstring):
    with load_romfs_into_bytesio() as mem:
        mem.seek(seek)
        mem.write(data)
        mem.seek(0)

        with pytest.raises(exc) as excinfo:
            romfs.RomFSReader(mem)

        assert excstring == str(excinfo.value)
