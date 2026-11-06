"""Enums and models used by indexes."""

from enum import Enum
from typing import Any, NotRequired, TypedDict, Unpack

from pydantic import BaseModel, ConfigDict, Field


class IndexType(Enum):
    """Index types for MongoDB collections."""

    TEXT = "text"
    GEOSPATIAL = "geospatial"
    HASHED = "hashed"


class IndexDirection(Enum):
    """Index directions for MongoDB collections."""

    ASCENDING = 1
    DESCENDING = -1


class _IndexKwargs(TypedDict):
    unique: NotRequired[bool]
    hidden: NotRequired[bool]


# https://www.mongodb.com/docs/manual/reference/command/createIndexes/#example
class Index(BaseModel):
    """Represents a MongoDB index document."""

    def __init__(
        self, name: str,
        key: dict[str, IndexType | IndexDirection],
        **kwargs: Unpack[_IndexKwargs],
    ) -> None:
        BaseModel.__init__(self, name=name, key=key, **kwargs)

    model_config = ConfigDict(use_enum_values=True)

    name: str
    key: dict[str, IndexType | IndexDirection]
    unique: bool = Field(default=False)
    hidden: bool = Field(default=False)

    def to_dict(self) -> dict[str, Any]:
        """Return the model as a dictionary."""
        return self.model_dump()
