from kover import __version__

from setuptools import setup  # type: ignore

setup(
    name="kover",
    version=__version__,
    install_requires=["pymongo", "attrs", "typing-extensions"],
    packages=['kover'],
    description="fully async mongodb driver for mongod and replica sets",
    author="oMegaPB",
    url="https://github.com/oMegaPB/kover"
)
