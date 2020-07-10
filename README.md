# PyCTR
Python library to interact with Nintendo 3DS files.

The API is not yet stable. If you decide to use this, you should stick to a specific version on pypi, or store a copy locally, until it is stable.

This was recently separated out to its own repository. This will be a better README at some point.

## Supported types
* CDN contents ("tmd" next to other contents)
* CTR Cart Image (".3ds", ".cci")
* CTR Importable Archive (".cia")
* Executable Filesystem (".exefs", "exefs.bin")
* NCCH (".cxi", ".cfa", ".ncch", ".app")
* Read-only Filesystem (".romfs", "romfs.bin")
* SD card filesystem ("Nintendo 3DS" directory)
* SMDH icon ("*.smdh", "icon.bin")
* Title Metadata ("*.tmd")

## License
`pyctr` is under the MIT license.
