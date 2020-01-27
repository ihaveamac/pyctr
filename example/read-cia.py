# This example demonstrates how to extract various kinds of data from a CTR Importable Archive (CIA) file.
# The file used in this example is Checkpoint 3.7.4. The CIA file can be obtained here:
# https://github.com/FlagBrew/Checkpoint/releases/tag/v3.7.4

# Import the reader class for CIA files.
from pyctr.type.cia import CIAReader, CIASection

# Import the json library to parse an example json file.
import json

# Open the file for reading. This will parse the ticket, title metadata, and contents including NCCH, ExeFS, and RomFS.
# If the file is encrypted and the appropriate keys are supplied, decryption is done on the fly.
with CIAReader('Checkpoint.cia') as cia:

    # cia.tmd is a TitleMetadataReader object which parses Title metadata (TMD) data.
    # TMD format information: https://www.3dbrew.org/wiki/Title_metadata

    # This will print out the Title ID from the TMD. This is a 16-character hex string.
    # In the case of Checkpoint this will appear as '000400000bcfff00'.
    print('Title ID:', cia.tmd.title_id)

    # The title version is stored in a TitleVersion object.
    # This will display it as major.minor.micro.
    # This version of Checkpoint has the title version 3.7.4.
    print('Title Version:', '{0.major}.{0.minor}.{0.micro}'.format(cia.tmd.title_version))

    # cia.contents is a dict with key as Content ID and value as an NCCHReader (if this is not a TWL/DSi title).
    # NCCH format information: https://www.3dbrew.org/wiki/NCCH

    # This title only has one content with an ID of 0, the application. This contains the executable code and
    #   filesystem used by the title.
    # Other common sections for executable titles include 1 for manual and 2 for dlpchild.
    app = cia.contents[CIASection.Application]

    # app.exefs is an ExeFSReader object which parses Executable Filesystem (ExeFS) data.
    # ExeFS format information: https://www.3dbrew.org/wiki/ExeFS

    # app.exefs.icon is an SMDH object which contains information such as the application title and icon.
    # This exists if there is a valid icon file in the ExeFS.
    # SMDH format information: https://www.3dbrew.org/wiki/SMDH

    # This will get the English information from the SMDH and return it as an AppTitle object.
    app_title = app.exefs.icon.get_app_title('English')

    # This will print the short description (the applicaton name) for the application.
    # With the example CIA this would be "Checkpoint".
    print('Application Title:', app_title.short_desc)

    # This will print the long description for the application.
    # With the example CIA this would be "Fast and simple save manager".
    print('Application Description:', app_title.long_desc)

    # This will print the publisher for the application.
    # With the example CIA this would be "Bernardo Giordano, FlagBrew".
    print('Application Publisher:', app_title.publisher)

    # app.romfs is an RomFSReader object which accesses files in the Read-Only Filesystem (RomFS).
    # RomFS format information: https://www.3dbrew.org/wiki/RomFS

    # This will get information about the path '/' which is a directory.
    # This would return a RomFSDirectoryEntry.
    # In this example the directory contents are printed out, which will be "gfx, cheats, config.json, PKSM.smdh".
    print('Contents in the root:', ', '.join(app.romfs.get_info_from_path('/').contents))

    # This will get information about the path '/config.json' which is a file.
    # This would return a RomFSFileEntry.
    # In this example the size is shown, which is 183 bytes.
    print('Size of /config.json in bytes:', app.romfs.get_info_from_path('/config.json').size)

    # This will parse the json file and print a value from it.
    # This demonstrates how to open files in the RomFS. The result is either a SubsectionIO object for binary, or
    #   one wrapped with io.TextIOWrapper for text.
    # By default, files open in binary mode. Specifying the encoding argument will open in text mode.
    with app.romfs.open('/config.json', encoding='utf-8') as f:
        config = json.load(f)

    # Print the config version, which is 3 for this title version.
    print('Config version:', config['version'])
