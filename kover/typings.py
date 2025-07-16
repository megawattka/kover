from pathlib import Path
from types import UnionType  # type: ignore  # noqa: F401
from typing import (
    Any,
    BinaryIO,
    Literal,
    TextIO,
)

from bson import SON

xJsonT = dict[str, Any]  # noqa: N816
DocumentT = xJsonT | SON[str, Any]

# TODO @megawattka: implement compression
COMPRESSION_T = list[Literal["zlib", "zstd", "snappy"]]

GridFSPayloadT = bytes | str | BinaryIO | TextIO | Path
