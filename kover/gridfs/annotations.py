"""Types for kover gridfs module."""

from collections.abc import AsyncIterable
from pathlib import Path
from typing import BinaryIO, TextIO

GridFSPayloadT = bytes | str | BinaryIO | TextIO | Path | AsyncIterable[bytes]
