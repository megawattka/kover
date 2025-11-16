"""Operation models, required by kover."""

from __future__ import annotations

from pydantic import BaseModel
from typing_extensions import NotRequired, TypedDict, Unpack

from ..helpers import filter_non_null
from ..internals.mixins import ModelMixin as _ModelMixin
from ..typings import xJsonT  # noqa: TC001
from .other import Collation  # noqa: TC001


class _UpdateKwargs(TypedDict):
    """Kwargs used in Update model."""

    upsert: NotRequired[bool]
    multi: NotRequired[bool]
    collation: NotRequired[Collation | None]
    array_filters: NotRequired[xJsonT | None]
    hint: NotRequired[str | None]


# https://www.mongodb.com/docs/manual/reference/command/update/#syntax
class Update(_ModelMixin):
    """Represents a MongoDB update document."""

    def __init__(
        self,
        q: xJsonT,
        u: xJsonT,
        c: xJsonT | None = None,
        /,
        **kwargs: Unpack[_UpdateKwargs],
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


class _DeleteKwargs(TypedDict):
    """Kwargs used in Delete model."""

    limit: int
    collation: NotRequired[Collation | None]
    hint: NotRequired[xJsonT | str | None]


# https://www.mongodb.com/docs/manual/reference/command/delete/#syntax
class Delete(_ModelMixin):
    """Represents a MongoDB delete document."""

    def __init__(self, q: xJsonT, /, **kwargs: Unpack[_DeleteKwargs]) -> None:
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
            "multi": self.limit != 1,
            "hint": self.hint,
            "collation": self.collation,
        })
