import datetime
from typing import Optional, Dict, Any

from bson import ObjectId, Binary

from ..schema import Document, field


class Chunk(Document):
    files_id: ObjectId
    n: int = field(min=0)
    data: bytes = field(converter=Binary, repr=False)


class File(Document):
    chunk_size: int = field(field_name="chunkSize", min=0)
    length: int
    upload_date: datetime.datetime = field(field_name="uploadDate")
    filename: Optional[str] = None
    metadata: Dict[str, Any] = field(
        default=None,
        converter=lambda val: val or {}  # type: ignore
    )
