import sys
from typing import (
    Dict,
    Any,
    Union,
    Literal,
    List
)

from bson import SON

xJsonT = Dict[str, Any]
DocumentT = Union[xJsonT, SON[str, Any]]
COMPRESSION_T = List[
    Literal["zlib", "zstd", "snappy"]
]  # TODO: implement

if sys.version_info < (3, 10):
    UnionType = Union
else:
    from types import UnionType # noqa: F401, E261 # type: ignore
