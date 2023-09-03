# PyCTR
Python library to interact with Nintendo 3DS files.

The API is not yet stable. If you decide to use this, you should stick to a specific version on pypi, or store a copy locally, until it is stable.

Documentation is being updated over time and is published on [Read the Docs](https://pyctr.readthedocs.io/en/latest/). Most classes and functions have docstrings.

Support is provided on [GitHub Discussions](https://github.com/ihaveamac/pyctr/discussions) or Discord ([info](https://ihaveahax.net/view/Discord), [invite link](https://discord.gg/YVuFUrs)).

## Supported types
* Application metadata and containers
  * CDN contents ("tmd" next to other contents)
  * CTR Cart Image (".3ds", ".cci")
  * CTR Importable Archive (".cia")
  * NCCH (".cxi", ".cfa", ".ncch", ".app")
  * Title Metadata ("*.tmd")
  * SMDH icon ("*.smdh", "icon.bin")
* Application contents
  * Executable Filesystem (".exefs", "exefs.bin")
  * Read-only Filesystem (".romfs", "romfs.bin")
* User files
  * NAND ("nand.bin")
  * SD card filesystem ("Nintendo 3DS" directory)
  * DISA (save) and DIFF (extdata) containers
    * NOT the Inner Fat yet! This is for the wrappers around them.

## License
`pyctr` is under the MIT license.
