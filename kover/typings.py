"""Kover Typings Module."""

from pathlib import Path
from typing import (
    Any,
    BinaryIO,
    Final,
    Literal,
    Protocol,
    TextIO,
    runtime_checkable,
)

from bson import SON

JsonT = dict[str, Any]
DocumentT = JsonT | SON[str, Any]

COMPRESSION_T = list[Literal["zlib", "zstd", "snappy"]]
GridFSPayloadT = bytes | str | BinaryIO | TextIO | Path
AuthTypesT = Literal["SCRAM-SHA-1", "SCRAM-SHA-256"]


@runtime_checkable
class HasToDict(Protocol):
    """Protocol for objects that can be converted to a dictionary."""

    def to_dict(self) -> JsonT:
        ...


class CompressionContext(Protocol):
    """Base Protocol for all compression contexts."""

    def compress(self, payload: bytes) -> bytes:
        ...

    def decompress(self, payload: bytes) -> bytes:
        ...


DEFAULT_MONGODB_PORT: Final[int] = 27017
