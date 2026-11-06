"""Types for kover gridfs module."""

from pathlib import Path
from typing import BinaryIO, TextIO

GridFSPayloadT = bytes | str | BinaryIO | TextIO | Path
