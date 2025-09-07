"""Operation models, required by kover."""

from __future__ import annotations

from pydantic import BaseModel

from .._internals._mixins import ModelMixin as _ModelMixin
from ..helpers import filter_non_null
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
    c: xJsonT | None = None  # constants
    upsert: bool = False
    multi: bool = False
    collation: Collation | None = None
    array_filters: xJsonT | None = None
    hint: str | None = None

    def as_bulk_write_op(self) -> xJsonT:
        """Serialize This model for BulkWriteBuilder.

        Returns:
            Serialized operation.
        """
        return filter_non_null({
            "filter": self.q,
            "updateMods": self.u,
            "arrayFilters": self.array_filters,
            "multi": self.multi,
            "hint": self.hint,
            "constants": self.c,
            "collation": self.collation,
        })


# https://www.mongodb.com/docs/manual/reference/command/delete/#syntax
class Delete(_ModelMixin):
    """Represents a MongoDB delete document."""

    def __init__(self, q: xJsonT, /, **kwargs: object) -> None:
        BaseModel.__init__(self, q=q, **kwargs)

    q: xJsonT  # query
    limit: int
    collation: Collation | None = None
    hint: xJsonT | str | None = None

    def as_bulk_write_op(self) -> xJsonT:
        """Serialize This model for BulkWriteBuilder.

        Returns:
            Serialized operation.
        """
        return filter_non_null({
            "filter": self.q,
            "multi": False if self.limit == 1 else True,
            "hint": self.hint,
            "collation": self.collation,
        })
