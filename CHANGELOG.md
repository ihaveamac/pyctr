## Next
### Highlights
A command line tool was added, `pyctr.cmd` with entrypoint `pyctrcmd`.

[PyFilesystem2](https://www.pyfilesystem.org/) (fs) is now a dependency.
* `RomFSReader` is now based on `fs.base.FS`
* `pyctr.type.sdfs` is a replacement for `pyctr.type.sd` that uses `fs.base.FS`
* `NAND` now contains 3 new methods: `open_ctr_fat`, `open_twl_fat`, and `open_bonus_fat`
* Most types that accept a file path or file-like object now accept an `fs=` argument, which can be an FS URL or a filesystem. For example:
  * `CIAReader('mygame.cia', fs='zip://path/to/mygame.zip')`
  * `CDNReader('tmd', fs=fs.zipfs.ZipFS('mycdngame.zip'))`
* Fix setting TWLNAND key for dev consoles (thanks to @xprism1 for assistance)

### Deprecation warnings
* `RomFSReader` was updated to use PyFilesystem2.
  * To match PyFilesystem2, the function signature for `open` has changed to add `mode` and `buffering` arguments between `path` and `encoding`. This also means opening files is done in text mode by default. For compatibility, if the second argument is detected to be an encoding, the file will be opened like before, and a `DeprecationWarning` will be raised.
  * `get_info_from_path` is deprecated and should be replaced with `getinfo`, `listdir`, or `scandir`.
* `pyctr.type.sdfs` was created to replace `pyctr.type.sd`, which is now deprecated.
  * `sdfs` uses PyFilesystem2. The one deviation from the standard is that `SDFS.open` will only open files in binary mode.

### Changelog
* Add initial pyctr command line tool, `pyctr.cmd` (entry point `pyctrcmd`) with one command, `checkenv`
* Move `seeddb_paths` to `pyctr.crypto.seeddb` from a function, making it publicly accessible (and then use it in `pyctr.cmd.checkenv`)
* `pyctr.crypto.engine` now includes a new function, `setup_boot9_keys`, which loads the keyblobs from boot9 instead of doing that within `CryptoEngine`
  * `CryptoEngine` now generates the keys from the global key blobs on initialization
  * This should also fix issues with separate retail and dev versions of `CryptoEngine` being used (some keys stored globally only stored one type of key)
  * `CryptoEngine.setup_keys_from_boot9` and `CryptoEngine.setup_keys_from_boot9_file` will now output a deprecation warning
* `CryptoEngine.setup_keys_from_otp` will now only update normal keys and set `otp_dec` and `otp_enc` at the end
* Add `CryptoEngine.clone` method to create a copy of the `CryptoEngine` state
* `CDNReader` and `CIAReader` will now clone their `CryptoEngine` state for each `NCCHReader`
* Use `fs.base.FS` for `RomFSReader`
  * fs (PyFilesystem2) is now a dependency
  * Tests have been updated to use the new FS methods
* Create `pyctr.type.sdfs` as a replacement for `pyctr.type.sd`
* Implement `open_ctr_fat`, `open_twl_fat`, and `open_bonus_fat` in `NAND`
  * pyfatfs is now a dependency
* Implement loading from SD in remaining types
* Add new example for getting version from a NAND backup
* `NANDNCSDHeader` can be converted back to bytes with `bytes(my_nand_header)`
* Include NAND sighax signatures as the `SIGHAX_SIGS` constant
* Always set fixed keys regardless of boot9 (in particular: TWLNAND Y, CTRNANDNew Y, ZeroKey N, FixedSystemKey N)

## v0.7.0 - September 3, 2023
### Highlights
Python 3.8 or later is now required, up from 3.6.1.

A new `pyctr.type.config` package with `save` and `blocks` modules was added. These allow for reading the [config savegame](https://www.3dbrew.org/wiki/Config_Savegame), both to read the raw blocks, and to parse the data into a usable format.

A new `nand` module with the `NAND` class is added to read and write to NAND images. This only provides raw access (for FAT32, try [nathanhi/pyfatfs](https://github.com/nathanhi/pyfatfs)).

`RomFSReader` initialization performance was improved, especially with RomFS files containing large amounts of files or directories.

Documentation is being added and improved over time. Check it on [Read the Docs](https://pyctr.readthedocs.io/en/latest/).

### Changelog
* Add the module `pyctr.type.configsave` with the class `ConfigSaveReader` (_module name changed in a future commit_)
* Implement `to_bytes` and `remove_block` in `ConfigSaveReader`
* Split `pyctr.type.configsave` into two packages: `pyctr.type.config.blocks` and `pyctr.type.config.save`
  * New `ConfigSaveBlockParser` class with 3 methods: `get_username`, `get_user_time_offset`, and `get_system_model` (plus convenience functions `load` and `from_file` so a `ConfigSaveParser` doesn't need to be manually created)
  * New enum: `SystemModel`
  * Both `ConfigSaveReader` and `ConfigSaveBlockParser` are importable from `pyctr.type.config`
* Add `flush` to `SubsectionIO`
* Optimize `CTRFileIO` to re-use existing cipher object when possible (seeking invalidates the current one)
* Optimize `RomFSReader` by reading entire directory and file metadata at once before traversing, significantly reducing the amount of read calls to the underlying file
* Optimize `RomFSReader` to reduce the read calls for the header (once for raw lv3, twice for IVFC)
* Check for unformatted saves in `DISA` (the first 0x20 bytes are all NULL and the rest is garbage)
* Remove `crypto_method == 0` check for NCCH files using `fixed_crypto_key`
* Add `nand` module with `NAND` class, to read and write to a NAND image
* Add `__slots__` to a bunch of classes (`CCIReader`, `CDNReader`, `CIAReader`, `ExeFSReader`, `NAND`, `NCCHReader`, `RomFSReader`, `SDFilesystem`, `SDTitleReader`, `SMDH`, `ConfigSaveReader`, `TypeReaderBase`, `TypeReaderCryptoBase`)
* Update copyright year
* Various documentation and type hint changes
  * Add new `FilePath` and `FilePathOrObject` types
* Add `__slots__` to `SubsectionIO` and `SplitFileMerger`
* Add some tests for `romfs` and `smdh`
* Load all boot9 keys in `CryptoEngine.setup_keys_from_boot9`
* Moved package metadata to `setup.cfg`
* Fix setting fixed keys in `CryptoEngine` and add debug logging to key setting
* Separate NCSD header loading from `NAND` to a separate class `NANDNCSDHeader`
* Refactor the `nand` module and `NAND` class:
  * Add support for virtual sections (things that are not NCSD partitions)
  * Rename `open_ncsd_partition` to `oprn_raw_section`
  * Add custom section IDs that always point to the correct partition, regardless of its physical location
  * Add custom section ID for GodMode9 bonus volume
* Add documentation files created with sphinx-autodoc
* Switch Sphinx theme to rtd, add example-cia, add info to index page
* Move RomFS header loading in `RomFSReader` to a new `RomFSLv3Header` class
* Many different documentation changes or additions
* Require Python 3.8
* Create new and update documentation pages - `example-nand` and `pyctr.type.nand`
* Fix `closefd` being default to True always in `NAND`
* Create documentation page for `pyctr.type.sd`
* Create documentation page for `pyctr.fileio`
* Create documentation page for `pyctr.util`
* Fixes to `ConfigSaveReader`:
  * `data_offset` is not hardcoded to `0x41E4`, it's based on the amount of data from the blocks
  * CFG adds data to save from end to start when the block data is > 4 bytes, so now we are replicating this behavior and generating a proper `data_offset` and data sorting when using `to_bytes`
  * Added sanity checks while parsing a config save
  * `set_block` previously didn't allowed `None` in flags despite being stated to default to `0xE`
* New attribute for SMDH: `SMDH.region_lockout`, with a new NamedTuple `SMDHRegionLockout`
* New attribute for CCIReader: `CCIReader.cart_region`, with a new Enum `CCICartRegion`
* `ConfigSaveReader.set_block` will now check Block IDs, flags, and sizes against a known list of blocks
  * Passing `strict=True` to `set_block` will bypass this
* `KNOWN_BLOCKS` in `pyctr.type.config.save` was changed to have values be dicts with "flags" and "size" keys (instead of plain tuples)
* Switch `get_*` and `set_*` to getters and setters in `pyctr.type.config.blocks
  * e.g. `username` instead of `get_username` and `set_username`
* Add new `from_bytes` and `__bytes__` methods to `AppTitle` to load title structures (and modify `SMDH` to use this now)

## v0.6.0 - January 26, 2022
### Highlights
Pillow is now an optional dependency. It is available through the extra feature `images`. This means to use `pyctr[images]` when adding to `setup.py`, `requirements.txt`, or `pip install`.

SMDH icon data is stored into an array like `[[(1, 2, 3), (4, 5, 6), ...]]`. It can be used with other libraries like the pure-python pypng, for example:

```python
from pyctr.type.cia import CIAReader
from itertools import chain
import png

my_cia = CIAReader('game.cia')

# pypng expects an array like [[1, 2, 3, 4, 5, 6, ...]] so we need to flatten the inner lists
img = png.from_array(
  (chain.from_iterable(x) for x in my_cia.contents[0].exefs.icon.icon_large_array),
  'RGB', {'width': 48, 'height': 48}
)
img.save('icon.png')
```

### Changelog
* Move around object attribute initialization in cci, cdn, cia, and sdtitle, to prevent extra exceptions if an error is raised early
* Use `open_raw_section` internally when initializing a `CIAReader` object, instead of manually seeking and reading
* Make Pillow an optional dependency and make SMDH load icon data into an array (useful for other libraries like pypng)
  * New functions in `smdh`: `rgb565_to_rgb888_tuple`, `load_tiled_rgb565_to_array`, `rgb888_array_to_image`
  * Init arguments for `SMDH` were changed to accept icon data arrays instead of Pillow `Image` objects
  * Pillow is added to `extras_require` under the feature `images`
* Documentation tweaks to `smdh`
* Remove unused import in `cia`

## v0.5.1 - June 28, 2021
* Fix arbitrary reads in the first 0x10 block of `CBCFileIO`

## v0.5.0 - June 26, 2021
### Highlights
A new `sdtitle` module with `SDTitleReader` is added to read titles installed on an SD card. When used directly, it works with contents that are not SD encrypted. To open a title on a 3DS SD card that is SD encrypted, a new method is added to `sd.SDFilesystem`: `open_title`.

SMDH icons are now loaded using [Pillow](https://python-pillow.org/).

SMDH flags are now loaded.

The ExeFS in NCCH contents is now fully decrypted properly. This means there is no longer garbage at the last block of the `.code` section for titles that use extra NCCH keys. This was achieved by rewriting the ExeFS section to concatenate multiple file-like objects that use different keyslots with a new class, `SplitFileMerger`.

### Changelog
* Add `_raise_if_file_closed_generic` to `pyctr.common`
* Add `SplitFileMerger` to `pyctr.fileio` to merge multiple file-like objects into one (currently no support for writing)
* Support closing all subfiles in `SplitFileMerger`
* Rewrite ExeFS handling in `NCCHReader` to use `SplitFileMerger` to merge multiple `SubsectionIO` files to handle the parts that use different encryption, and update `FullDecrypted` to use it when reading ExeFS
* Add `from_bytes` classmethod to `NCCHFlags`
* Always use the internal ExeFS file object when reading it for FullDecrypted
* Add docstrings to `NCCHFlags`
* Add dependency on `Pillow>=8.2`
* Load SMDH icons using Pillow/PIL, stored in new attributes in the `SMDH` class: `icon_small`, `icon_large`
* Load SMDH flags into a new `SMDHFlags` class
* Add `isfile` and `isdir` methods to `SDFilesystem`, convert path to string in `sd.normalize_sd_path` to make it easier to use any `os.PathLike` object (e.g. `pathlib.PurePosixPath`)
* Add `sdtitle` module with `SDTitleReader` class, to read titles installed to the SD card inside "Nintendo 3DS"
* Add `open_title` method to `SDFilesystem` to open a title using `SDTitleReader`, and a new `MissingTitleError` exception
* Update type hints in `sd`

## v0.4.7 - April 20, 2021
* Use absolute paths in `CDNReader`
* Use absolute paths in `SDFilesystem`
* Make `SubsectionIO` objects hashable (if the underlying file object is)
* Make sure two different `CTRFileIO`, `TWLCTRFileIO`, and `CBCFileIO` return different hashes, even with the same reader + key + iv/counter
* Add `TWLCTRFileIO` to `crypto.engine.__all__`
* Use a `frozenset` on a closed `CDNReader` object's internal open files set
* Don't set `__del__` directly to `close` in `TypeReaderBase`, in case `close` is overridden
* Auto-close opened files based on a reader when the reader closes (applies to `CCIReader`, `CIAReader`, `ExeFSReader`, `NCCHReader`, and `RomFSReader`)
* Add new pseudo-keyslot `NCCHExtraKey` to store the second keyslot data for NCCH contents
  * This is important because there exist titles that use Original NCCH but with a seed. Before this change, the key in the `NCCH` keyslot would be overwritten, causing everything but the special regions (ExeFS .code and RomFS) to be improperly decrypted.
* Use `NCCHExtraKey` for the second keyslot instead of the actual keyslot in `NCCHReader`
* Set `_open_files` before opening the file in `TypeReaderBase` to prevent an additional error if opening the file fails
* Don't set KeyX and KeyY separately if fixed crypto key is used without an extra crypto method
* Fix sections in `CCIReader` not opening, raising an error

## v0.4.6 - March 1, 2021
* Add pycryptodomex version requiremenet range (`>=3.9,<4`)
* Fix using bytes file paths for `CDNReader` and `SDFilesystem`
* Support auto-closing underlying file for `CTRFileIO` and `CBCFileIO`
* Make `CTRFileIO` and `CBCFileIO` objects hashable (if the underlying file object is)
* Update `CDNReader` to re-open files instead of using shared file objects, and internally open all files through `CDNReader.open_raw_section` (fixes #6)
* Store encrypted and decrypted OTP in `CryptoEngine` as `otp_enc` and `otp_dec`, and add `otp_keys_set` to check if an OTP was set
* Verify OTP magic after decryption in `CryptoEngine.setup_keys_from_otp`
* Make `CryptoEngine.otp_device_id` require OTP (raising an exception instead of returning None)
* Add `TWLCTRFileIO` as a subclass of `CTRFileIO` which handles the special read/write crypto specific to TWLNAND

## v0.4.5 - October 24, 2020
* Fix loading RomFS from a filename in `RomFSReader`
* Fix loading ExeFS from a filename in `ExeFSReader`

## v0.4.4 - September 20, 2020
* Support loading a decrypted titlekey for `CDNReader`
* Remove unused `sections` attribute from `CDNReader`
* Add `available_sections` to `CDNReader` to provide a list of sections available in the title
* Add `__author__`, `__copyright__`, `__license__`, `__version__`, and `version_info` to `pyctr.__init__`

## v0.4.3 - July 28, 2020
* Fix endianness issue when converting a `TitleMetadataReader` object to `bytes`

## v0.4.2 - July 28, 2020
* Don't assume a Cygwin environment is Windows
* Change keyslot for New 3DS key sector keys from 0x11 to 0x43
  * This adds a new Keyslot enum item: `Keyslot.New3DSKeySector`
* Document more methods in pyctr.crypto.engine
* Add new `fileio.CloseWrapper` class to provide access to a file object while preventing closing it directly
* Use `CloseWrapper` in `CDNReader.open_raw_section`

## v0.4.1 - July 11, 2020
* Support NCCH contents with fixed crypto key (zerokey and fixed system key)
  * CryptoEngine adds these to fake keyslots 0x41 and 0x42 respectively.
* Fixed setting up keyslot 0x11, used for decrypting the New 3DS key sector

## v0.4.0 - July 10, 2020
* Add DISA/DIFF reading and writing under `pyctr.type.save`
  * This does NOT include Inner FAT support yet.
  * This can read and write to IVFC level 4. For now, external tools can be used to read or write to the Inner FAT.
* Add CDN reading under `pyctr.type.cdn`
* Add more docstrings to various modules
* Add seed parameters to ncch, cia, and cdn
* Rename `Keyslot.UDSLocalWAN` to `Keyslot.UDSLocalWLAN`
* Many other internal changes done months ago

## v0.3.1 - April 8, 2020
* Fix `setup.py` not including subpackages

## v0.3.0 - April 8, 2020
* Document more classes, methods, and attributes
* Add a `pyctr.crypto.seeddb` module for central SeedDB management
  * Loading SeedDB in `NCCHReader` is now removed
* Add new `TypeReaderBase` and `TypeReaderCryptoBase` for reader types that use a single file
* Fix `PathLike` error in `NCCHReader` and `RomFSReader`
* Changed type of `partition_id` and `program_id` in `NCCHReader` to `str`
* Some other changes. I'll get better at documenting this!

## v0.2.1 - April 3, 2020
* Remove debug print in `SDFilesystem.open`

## v0.2.0 - April 3, 2020
* Add the module `pyctr.type.sd` with the class `SDFilesystem`
* Add docstrings to `pyctr.crypto`
* Allow `os.PathLike`, `str`, and `bytes` as file paths in most methods
* Allow Windows-style paths in `CryptoEngine.sd_path_to_iv`

## v0.1.0 - January 27, 2020
Initial standalone release. All previous commits are in the [ninfs](https://github.com/ihaveamac/ninfs) repo.
