# This example demonstrates how to get the version (specifically, CVer and NVer) from a NAND backup.
# No example file is provided here, you need to get your own NAND dump.

# Import argv so we can specify our own NAND file as an argument.
from sys import argv

# Import the reader class for NAND files.
from pyctr.type.nand import NAND

# Import exceptions that may be raised when trying to search for tmds.
from fs.errors import ResourceNotFound

# Import the reader class for SD titles. Despite the name, this also works for titles on the NAND.
from pyctr.type.sdtitle import SDTitleReader

# This is all for type hints. This is to make it easier to understand what objects are being passed around.
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from typing import BinaryIO
    from fs.base import FS


# This function will try to search multiple folders for a file that ends in *.tmd and get the first one.
# This does not use glob because that is a lot slower than searching the directories ourselves.
# Potential edge cases that you can solve:
#  * What if none is found?
#  * What if multiple tmds are found? This can happen if an update is pre-downloaded but not applied.
def find_tmd(fs: 'FS', tid_high: 'str', tid_lows: 'list[str]'):
    for low in tid_lows:
        path = f'/title/{tid_high}/{low}/content'
        try:
            filelist = fs.scandir(path)
        except ResourceNotFound:
            continue
        else:
            for f in filelist:
                if f.name.endswith('.tmd'):
                    return path + '/' + f.name
    else:
        return None


# This reads version.bin, found in both CVer and NVer RomFS.
# Both have the same format, but CVer has 4 values we care about, while NVer has 2 (first 2 we can ignore).
# Version number is in order of build, minor, major.
# To make this convenient for our code, we will reverse it to the expected order.
def read_versionbin(fp: 'BinaryIO'):
    data = fp.read(5)
    return data[2], data[1], data[0], chr(data[4])


# Open the NAND for reading.
print('Opening', argv[1])
with NAND(argv[1]) as nand:

    # Open the FAT16 filesystem in CTR NAND.
    print('Opening CTR NAND FAT16')
    ctrfat = nand.open_ctr_fat()

    # Try to find the CVer tmd file.
    # CVer is different for each region (6 possible titles).
    print('Attempting to find CVer tmd...')
    cver_lows = ['00017102', '00017202', '00017302', '00017402', '00017502', '00017602']
    cver_tmd = find_tmd(ctrfat, '000400db', cver_lows)

    # Try to find the NVer tmd file.
    # NVer is different for each region and Old / New 3DS (10 possible titles).
    print('Attempting to find NVer tmd...')
    nver_lows_old = ['00016102', '00016202', '00016302', '00016402', '00016502', '00016602']
    nver_lows_new = ['20016102', '20016202', '20016302', '20016502']
    nver_tmd = find_tmd(ctrfat, '000400db', nver_lows_old + nver_lows_new)

    print('CVer tmd:', cver_tmd)
    print('NVer tmd:', nver_tmd)

    with SDTitleReader(cver_tmd, fs=ctrfat) as cver:
        with cver.contents[0].romfs.open('version.bin', 'rb') as f:
            cver_info = read_versionbin(f)

    with SDTitleReader(nver_tmd, fs=ctrfat) as nver:
        with nver.contents[0].romfs.open('version.bin', 'rb') as f:
            nver_info = read_versionbin(f)

    print('{0[0]}.{0[1]}.{0[2]}-{1[0]}{1[3]}'.format(cver_info, nver_info))
