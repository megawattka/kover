from __future__ import annotations

import datetime  # noqa: TC003
from typing import Annotated

from bson import Binary, ObjectId  # noqa: TC002
from pydantic import Field

from ..metadata import SchemaMetadata
from ..schema import Document


class Chunk(Document):
    """Represents a GridFS chunk document.

    Attributes:
    ----------
    files_id : ObjectId
        The id of the file this chunk belongs to.
    n : int
        The sequence number of the chunk (must be >= 0).
    data : Binary
        The binary data stored in this chunk.
    """

    files_id: ObjectId = Field(alias="files_id")
    n: Annotated[int, SchemaMetadata(minimum=0)]
    data: Binary = Field(repr=False)


class File(Document):
    """Represents a GridFS file document.

    Attributes:
    ----------
    length : int
        The length of the file in bytes.
    upload_date : datetime.datetime
        The date and time the file was uploaded in UTC.
    filename : str | None
        The name of the file.
    metadata : dict[str, object]
        Additional metadata associated with the file.
    chunk_size : int
        The size of each chunk in bytes.
    """

    length: int
    upload_date: datetime.datetime = Field(alias="upload_date")
    filename: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    chunk_size: Annotated[int, SchemaMetadata(minimum=0)] = Field(
        alias="chunk_size",
    )
