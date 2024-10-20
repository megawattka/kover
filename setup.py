from setuptools import setup

setup(
    name="kover",
    version="0.3.2",
    install_requires=["pymongo", "attrs"],
    packages=['kover'],
    description="fully async mongodb driver for mongod and replica set",
    author="oMegaPB",
    url="https://github.com/oMegaPB/kover",
)