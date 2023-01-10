# This file is a part of pyctr.
#
# Copyright (c) 2017-2023 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from os.path import dirname, join, realpath

import pytest

from pyctr.type import smdh


def get_file_path(*parts: str):
    return join(dirname(realpath(__file__)), *parts)


def open_smdh():
    return smdh.SMDH.from_file(get_file_path('fixtures', 'icon.bin'))


def test_no_file():
    with pytest.raises(FileNotFoundError):
        smdh.SMDH.from_file('nonexistant.bin')


smdh_params = (
    ('Japanese', 'japanese short title', 'japanese long description', 'j publisher'),
    ('English', 'english short title', 'english long description', 'e publisher'),
    ('French', 'french short title', 'french long description', 'f publisher'),
    ('German', 'german short title', 'german long description', 'g publisher'),
    ('Italian', 'italian short title', 'italian long description', 'i publisher'),
    ('Spanish', 'spanish short title', 'spanish long description', 's publisher'),
    ('Simplified Chinese', 'simplifiedchinese short title', 'simplifiedchinese long description', 'sc publisher'),
    ('Korean', 'korean short title', 'korean long description', 'k publisher'),
    ('Dutch', 'dutch short title', 'dutch long description', 'd publisher'),
    ('Portuguese', 'portuguese short title', 'portuguese long description', 'p publisher'),
    ('Russian', 'russian short title', 'russian long description', 'r publisher'),
    ('Traditional Chinese', 'traditionalchinese short title', 'traditionalchinese long description', 'tc publisher'),
)


@pytest.mark.parametrize('language,short,long,pub', smdh_params)
def test_read_description(language, short, long, pub):
    reader = open_smdh()
    title = reader.get_app_title(language)
    assert isinstance(title, smdh.AppTitle)
    assert title.short_desc == short
    assert title.long_desc == long
    assert title.publisher == pub


def test_flags():
    reader = open_smdh()
    flags_expected = smdh.SMDHFlags(Visible=True, AutoBoot=True, Allow3D=True, SaveData=True, New3DS=True,
                                    RequireEULA=False, AutoSave=False, ExtendedBanner=False, RatingRequired=False,
                                    RecordUsage=False, NoSaveBackups=False)
    assert reader.flags == flags_expected


def test_incorrect_header():
    with pytest.raises(smdh.InvalidSMDHError) as excinfo:
        smdh.SMDH.from_file(get_file_path('fixtures', 'romfs.bin'))

    assert 'SMDH magic not found' in str(excinfo.value)
