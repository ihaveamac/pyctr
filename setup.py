from setuptools import find_packages, setup

with open('README.md', 'r', encoding='utf-8') as f:
    readme = f.read()

setup(
    name='pyctr',
    version='0.4.6',
    packages=find_packages(),
    install_requires=['pycryptodomex>=3.9,<4'],
    python_requires='>=3.6',
    url='https://github.com/ihaveamac/pyctr',
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
