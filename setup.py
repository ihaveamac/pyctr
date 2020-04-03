from setuptools import setup

with open('README.md', 'r', encoding='utf-8') as f:
    readme = f.read()

setup(
    name='pyctr',
    version='0.2.1',
    packages=['pyctr', 'pyctr.type'],
    install_requires=['pycryptodomex'],
    python_requires='>=3.6',
    url='https://git.ianburgwin.net/ianburgwin/pyctr',
    license='MIT',
    author='Ian Burgwin',
    author_email='ian@ianburgwin.net',
    description='Python library to parse several Nintendo 3DS files',
    long_description=readme,
    long_description_content_type='text/markdown',
    classifiers=[
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8'
    ]
)
