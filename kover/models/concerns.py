"""Write/Read concern for kover."""

from typing import Any, Literal

from pydantic import BaseModel


# https://www.mongodb.com/docs/manual/reference/write-concern/
class WriteConcern(BaseModel):
    """Represents a MongoDB write concern document."""

    w: str | int = "majority"
    j: bool | None = None
    wtimeout: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the write concern document."""
        return self.model_dump(exclude_none=True)


# https://www.mongodb.com/docs/manual/reference/read-concern/
class ReadConcern(BaseModel):
    """Represents a MongoDB read concern document."""

    level: Literal[
        "local",
        "available",
        "majority",
        "linearizable",
        "snapshot",
    ] = "local"

    def to_dict(self) -> dict[str, Any]:
        """Return the model as a dictionary."""
        return self.model_dump()
