from pathlib import Path
from types import UnionType  # type: ignore  # noqa: F401
from typing import Any, BinaryIO, Literal, Protocol, TextIO, runtime_checkable

from .bson import SON

xJsonT = dict[str, Any]  # noqa: N816
DocumentT = xJsonT | SON[str, Any]

COMPRESSION_T = list[Literal["zlib", "zstd", "snappy"]]
GridFSPayloadT = bytes | str | BinaryIO | TextIO | Path
AuthTypesT = Literal["SCRAM-SHA-1", "SCRAM-SHA-256"]


@runtime_checkable
class HasToDict(Protocol):
    """Protocol for objects that can be converted to a dictionary."""

    def to_dict(self) -> xJsonT:
        ...


class CompressionContext(Protocol):
    """Base Protocol for all compression contexts."""

    def compress(self, payload: bytes) -> bytes:
        ...

    def decompress(self, payload: bytes) -> bytes:
        ...
