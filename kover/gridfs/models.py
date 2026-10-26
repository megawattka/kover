"""Models for GridFS files and chunks."""

from __future__ import annotations

import datetime as dt  # ruff: ignore[typing-only-standard-library-import]
from typing import Annotated

from bson import Binary, ObjectId  # ruff: ignore[typing-only-third-party-import]
from pydantic import Field

from ..schema.document import Document


class Chunk(Document):
    """Represents a GridFS chunk document.

    Attributes:
        files_id : The id of the file this chunk belongs to.
        n : The sequence number of the chunk (must be >= 0).
        data : The binary data stored in this chunk.
    """

    files_id: ObjectId = Field(alias="files_id")
    n: Annotated[int, Field(ge=0)]
    data: Binary = Field(repr=False)


class File(Document):
    """Represents a GridFS file document.

    Attributes:
        length : The length of the file in bytes.
        upload_date : The date and time the file was uploaded in UTC.
        filename : The name of the file.
        metadata : Additional metadata associated with the file.
        chunk_size : The size of each chunk in bytes.
    """

    length: int
    upload_date: dt.datetime
    filename: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    chunk_size: Annotated[int, Field(ge=0)]
