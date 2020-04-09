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
