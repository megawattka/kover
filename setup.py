import sys
from pathlib import Path
from setuptools import setup  # type: ignore
from typing import Dict, Any

import kover
from kover import __version__, __author__

if sys.version_info < (3, 10):
    raise Exception(
        f"Unsupported python version: {sys.version_info}. 3.10 is required."
    )

cwd = Path.cwd()
package_dir = cwd.joinpath("kover")
requirements = cwd / "requirements.txt"
install_requires = requirements.open().read().splitlines()

kwargs: Dict[str, Any] = {
    "name": kover.__name__,
    "version": __version__,
    "install_requires": install_requires,
    "packages": [kover.__name__],
    "description": "fully async mongodb driver for mongod and replica sets",
    "author": __author__,
    "url": "https://github.com/oMegaPB/kover",
    "include_package_data": True,
    "data_files": [
        str(x.relative_to(cwd))
        for x in package_dir.joinpath("gridfs").iterdir()
        if x.name != "__pycache__"
    ]  # include "gridfs" dir into package
}

setup(**kwargs)
