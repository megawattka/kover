"""Operation models, required by kover."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .._internals._mixins import ModelMixin as _ModelMixin
from ..typings import xJsonT  # noqa: TC001
from .other import Collation  # noqa: TC001


# https://www.mongodb.com/docs/manual/reference/command/update/#syntax
class Update(_ModelMixin):
    """Represents a MongoDB update document."""

    def __init__(
        self,
        q: xJsonT,
        u: xJsonT,
        c: xJsonT | None = None,
        /,
        **kwargs: object,
    ) -> None:
        BaseModel.__init__(self, q=q, u=u, c=c, **kwargs)

    q: xJsonT
    u: xJsonT
    c: xJsonT | None = None
    upsert: bool = False
    multi: bool = False
    collation: Collation | None = None
    array_filters: xJsonT | None = None
    hint: str | None = None


# https://www.mongodb.com/docs/manual/reference/command/delete/#syntax
class Delete(_ModelMixin):
    """Represents a MongoDB delete document."""

    def __init__(self, q: xJsonT, /, **kwargs: object) -> None:
        BaseModel.__init__(self, q=q, **kwargs)

    q: xJsonT
    limit: Literal[0, 1]
    collation: Collation | None = None
    hint: xJsonT | str | None = None
