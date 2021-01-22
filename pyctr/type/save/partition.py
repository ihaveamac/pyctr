# This file is a part of pyctr.
#
# Copyright (c) 2017-2021 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE in the root of this project.

from typing import TYPE_CHECKING

from ...fileio import SubsectionIO
from .partdesc.difi import DIFI
from .partdesc.dpfs import DPFS, DPFSLevel1, DPFSLevel2, DPFSLevel3, DPFSLevel3FileIO
from .partdesc.ivfc import IVFC, IVFCHashTree

if TYPE_CHECKING:
    from typing import BinaryIO, Callable, List


def load_partdesc(partdesc: bytes):
    """
    Load a partition descriptor.

    :param partdesc: The partition descriptor. The first 0x44 must be a DIFI header. The rest is determined by the DIFI.
    """

    difi = DIFI.from_bytes(partdesc[0:0x44])
    ivfc = IVFC.from_bytes(partdesc[difi.ivfc_offset:difi.ivfc_offset + difi.ivfc_size])
    dpfs = DPFS.from_bytes(partdesc[difi.dpfs_offset:difi.dpfs_offset + difi.dpfs_size])
    base_master_hash = partdesc[difi.part_hash_offset:difi.part_hash_offset + difi.part_hash_size]
    master_hashes: List[bytes] = [base_master_hash[x:x + 0x20] for x in range(0, difi.part_hash_size, 0x20)]
    return difi, ivfc, dpfs, master_hashes


def partdesc_to_bytes(difi, ivfc, dpfs, master_hashes, size):
    partdesc = bytearray(size)

    difi_bytes = difi.to_bytes()
    ivfc_bytes = ivfc.to_bytes()
    dpfs_bytes = dpfs.to_bytes()
    master_hashes_bytes = b''.join(master_hashes)

    partdesc[0:len(difi_bytes)] = difi_bytes
    partdesc[difi.ivfc_offset:difi.ivfc_offset + len(ivfc_bytes)] = ivfc_bytes
    partdesc[difi.dpfs_offset:difi.dpfs_offset + len(dpfs_bytes)] = dpfs_bytes
    partdesc[difi.part_hash_offset:difi.part_hash_offset + len(master_hashes_bytes)] = master_hashes_bytes

    return bytes(partdesc)


class Partition:
    """
    Reads a partition found within DISA and DIFF files.

    :param fp: A file-like object with the partition data.
    :param difi: DIFI header from the partition descriptor.
    :param ivfc: IVFC descriptor from the partition descriptor.
    :param dpfs: DPFS descriptor from the partition descriptor.
    :param master_hashes: A list of SHA-256 hashes over IVFC Level 1.
    """

    def __init__(self, fp: 'BinaryIO', difi: 'DIFI', ivfc: 'IVFC', dpfs: 'DPFS', master_hashes: 'List[bytes]', *,
                 update_partdesc_callback: 'Callable[[bytes], None]' = None, partdesc_size: int = None):
        self._fp = fp
        self.difi = difi
        self.ivfc = ivfc
        self.dpfs = dpfs
        self.master_hashes = master_hashes

        if update_partdesc_callback:
            self._update_partdesc_callback = update_partdesc_callback
        else:
            self._update_partdesc_callback = lambda x: None

        if partdesc_size:
            self._partdesc_size = partdesc_size
        else:
            # if partdesc size isn't specified, let's assume what it usually is
            # the numbers are the sizes for DIFI, IVFC, and DPFS.
            self._partdesc_size = 0x44 + 0x78 + 0x40 + (0x20 * len(self.master_hashes))

        self._fp.seek(dpfs.lv1.offset)
        dpfs_lv1 = DPFSLevel1(self._fp.read(dpfs.lv1.size * 2), tree_selector=difi.dpfs_tree_lv1_selector)
        self._fp.seek(dpfs.lv2.offset)
        dpfs_lv2 = DPFSLevel2(self._fp.read(dpfs.lv2.size * 2), dpfs.lv2.block_size, dpfs_lv1)
        dpfs_lv3_base_file = SubsectionIO(self._fp, dpfs.lv3.offset, dpfs.lv3.size * 2)
        dpfs_lv3 = DPFSLevel3(dpfs_lv3_base_file, dpfs.lv3.size, dpfs.lv3.block_size, dpfs_lv2)

        self.dpfs_lv3_file = DPFSLevel3FileIO(dpfs_lv3)

        if difi.enable_external_ivfc_lv4:
            lv4_fp = SubsectionIO(self._fp, difi.external_ivfc_lv4_offset, ivfc.lv4.size)
        else:
            lv4_fp = None
        self.ivfc_hash_tree = IVFCHashTree(self.dpfs_lv3_file, self.ivfc, self.master_hashes, lv4_fp=lv4_fp,
                                           update_master_hashes_callback=self._update_hashes)

    def _update_hashes(self, master_hashes: 'List[bytes]'):
        self.master_hashes = master_hashes

        partdesc = partdesc_to_bytes(self.difi, self.ivfc, self.dpfs, self.master_hashes, self._partdesc_size)
        self._update_partdesc_callback(partdesc)
