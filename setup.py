import sys
from pathlib import Path
import pkg_resources
from setuptools import setup  # type: ignore
from typing import Dict, Any

import kover
from kover import __version__, __author__

if sys.version_info < (3, 10):
    raise Exception(
        f"Unsupported python version: {sys.version_info}. 3.10 is required."
    )

requirements = Path.cwd() / "requirements.txt"
install_requires = [
    req.name
    for req in pkg_resources.parse_requirements(requirements.open())
]

kwargs: Dict[str, Any] = {
    "name": kover.__name__,
    "version": __version__,
    "install_requires": install_requires,
    "packages": [kover.__name__],
    "description": "fully async mongodb driver for mongod and replica sets",
    "author": __author__,
    "url": "https://github.com/oMegaPB/kover"
}

setup(**kwargs)
