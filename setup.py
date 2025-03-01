import sys
from pathlib import Path
from setuptools import setup  # type: ignore
from typing import Dict, Any

if sys.version_info < (3, 10):
    raise Exception(
        f"Unsupported python version: {sys.version_info}. 3.10 is required."
    )


__version__ = "2.0.8"
__author__ = "oMegaPB"
cwd = Path.cwd()
package_dir = cwd.joinpath("kover")
requirements = cwd / "requirements.txt"
install_requires = requirements.open().read().splitlines()

kwargs: Dict[str, Any] = {
    "name": "kover",
    "version": __version__,
    "install_requires": install_requires,
    "packages": ["kover"],
    "description": "fully async mongodb driver for mongod and replica sets",
    "author": "oMegaPB",
    "url": "https://github.com/oMegaPB/kover",
    "include_package_data": True,
    "data_files": [
        str(x.relative_to(cwd))
        for z in [
            d.name for d in package_dir.iterdir()
            if d.is_dir() and d.name != "__pycache__"
        ] for x in package_dir.joinpath(z).iterdir()
        if x.name != "__pycache__"
    ],  # include other dirs into package
    "classifiers": [
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ],
}

setup(**kwargs)
