import datetime
from typing import Optional, Dict, Any, Annotated

from bson import ObjectId, Binary
from pydantic import Field

from ..schema import Document
from ..metadata import SchemaMetadata


class Chunk(Document):
    files_id: ObjectId = Field(alias="files_id")
    n: Annotated[int, SchemaMetadata(minimum=0)]
    data: Binary = Field(repr=False)


class File(Document):
    length: int
    upload_date: datetime.datetime = Field(alias="upload_date")
    filename: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    chunk_size: Annotated[int, SchemaMetadata(minimum=0)] = Field(
        alias="chunk_size"
    )
