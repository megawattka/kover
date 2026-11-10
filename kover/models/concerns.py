"""Write/Read concern for kover."""

from typing import Literal

from pydantic import BaseModel

from .._utils import ExcludeIfNone  # ruff: ignore[typing-only-first-party-import]


# https://www.mongodb.com/docs/manual/reference/write-concern/
class WriteConcern(BaseModel):
    """Represents a MongoDB write concern document."""

    w: str | int = "majority"
    j: ExcludeIfNone[bool] = None
    wtimeout: ExcludeIfNone[int] = None


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
