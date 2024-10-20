from setuptools import setup

setup(
    name="kover",
    version="0.7.1",
    install_requires=["pymongo", "attrs", "typing-extensions"],
    packages=['kover'],
    description="fully async mongodb driver for mongod and replica set",
    author="oMegaPB",
    url="https://github.com/oMegaPB/kover",
)