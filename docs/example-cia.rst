Example: Read contents from a CIA
=================================

In this example we will take a homebrew CIA file and extract some data from it. The example in this case will be Checkpoint 3.7.4. `Download the example title here. <https://github.com/FlagBrew/Checkpoint/releases/download/v3.7.4/Checkpoint.cia>`_

First we need to import :class:`~.CIAReader` and :class:`~.CIASection`. The former does the actual reading, the latter is an enum that can be used to access the contents. We will also import :py:mod:`json` to read a JSON file inside the RomFS.

.. code-block:: python

    >>> import json
    >>> from pyctr.type.cia import CIAReader, CIASection

Now we can open the file by creating a :class:`~.CIAReader` object.

.. code-block:: python

    >>> cia = CIAReader('Checkpoint.cia')

This will grant immediate access to all the contents inside, including the tmd, ticket, and NCCH contents. It also loads the data within the NCCH contents, such as the RomFS.

We can now check the Title ID by accessing it through the :attr:`tmd <pyctr.type.cia.CIAReader.tmd>` attribute:

.. code-block:: python

    >>> print('Title ID:', cia.tmd.title_id)
    Title ID: 000400000bcfff00

Let's also print the Title Version, using the :attr:`title_version <pyctr.type.tmd.TitleMetadataReader.title_version>` attribute.

.. code-block:: python

    >>> print('Title Version:', '{0.major}.{0.minor}.{0.micro}'.format(cia.tmd.title_version))
    Title Version: 3.7.4

Now let's access the executable content using the :attr:`contents <pyctr.type.cia.CIAReader.contents>` attribute. Here we'll use :attr:`CIASection.Application <pyctr.type.cia.CIASection.Application>` to read the first (and only) content.

.. code-block:: python

    >>> app = cia.contents[CIASection.Application]
    >>> app
    <NCCHReader program_id: 000400000bcfff00 product_code: CTR-HB-CKPT title_name: 'Checkpoint'>

This has given us an :class:`~.NCCHReader` object.

Let's get the application's SMDH, which will give us access to the name and publisher shown on the HOME Menu. We'll get it through the ExeFS and get an :class:`SMDH <pyctr.type.smdh.SMDH>` object.

.. code-block:: python

    >>> app_title = app.exefs.icon.get_app_title('English')
    >>> app_title
    AppTitle(short_desc='Checkpoint', long_desc='Fast and simple save manager', publisher='Bernardo Giordano, FlagBrew')
    >>> print('Application Title:', app_title.short_desc)
    Application Title: Checkpoint
    >>> print('Application Description:', app_title.long_desc)
    Application Description: Fast and simple save manager
    >>> print('Application Publisher:', app_title.publisher)
    Application Publisher: Bernardo Giordano, FlagBrew

Next, we will list the contents of the RomFS. The :class:`~.NCCHReader` has a :attr:`romfs <pyctr.type.ncch.NCCHReader.romfs>` attribute that will give us a :class:`RomFSReader <pyctr.type.romfs.RomFSReader>` object.

Using :func:`get_info_from_path <pyctr.type.romfs.RomFSReader.get_info_from_path>` we will list the contents at the root.

.. code-block:: python

    >>> print('Contents in the root:', ', '.join(app.romfs.get_info_from_path('/').contents))
    Contents in the root: gfx, cheats, config.json, PKSM.smdh

Using the same method, we can get information about a specific file.

.. code-block:: python

    >>> print('Size of /config.json in bytes:', app.romfs.get_info_from_path('/config.json').size)
    Size of /config.json in bytes: 183

Finally, we can open the file and parse the JSON inside. We'll pass an ``encoding`` argument so that we get an :py:class:`io.TextIOWrapper` object. Then we use :py:func:`json.load` and print a value from it.

.. code-block:: python

    >>> f = app.romfs.open('/config.json', encoding='utf-8')
    >>> f
    <_io.TextIOWrapper encoding='utf-8'>
    >>> config = json.load(f)
    >>> f.close()
    >>> config
    {'filter': [], 'favorites': [], 'additional_save_folders': {}, 'additional_extdata_folders': {}, 'nand_saves': False, 'scan_cart': False, 'version': 3}
    >>> print('Config version:', config['version'])
    Config version: 3

When you're done, make sure to close the :class:`~.CIAReader`. You should also close any open files based on the CIA.

.. code-block:: python

    >>> cia.close()

You can also use :class:`~.CIAReader` in the form of a context manager.

.. code-block:: python

    with CIAReader('Checkpoint.cia') as cia:
        with cia.contents[CIASection.Application].romfs.open('/config.json') as f:
            config = json.load(f)
            print('Config version:', config['version'])
