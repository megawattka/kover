from typing import Dict, Any, Union, Literal, List

from bson import SON

xJsonT = Dict[str, Any]
DocumentT = Union[xJsonT, SON]
COMPRESSION_T = List[Literal["zlib", "zstd", "snappy"]]