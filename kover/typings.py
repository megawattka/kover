from typing import Dict, Any, Union, Literal, TypeAlias, List

from bson import SON

xJsonT: TypeAlias = Dict[str, Any]
DocumentT: TypeAlias = Union[xJsonT, SON]
COMPRESSION_T: TypeAlias = List[Literal["zlib", "zstd", "snappy"]]