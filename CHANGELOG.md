## Next
* Add pycryptodomex version requiremenet range (`>=3.9,<4`)

## v0.4.5 - October 24, 2020
* Fix loading RomFS from a filename in `RomFSReader`
* Fix loading ExeFS from a filename in `RomFSReader`

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
