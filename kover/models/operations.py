"""Operation models, required by kover."""

from __future__ import annotations

from typing import NotRequired, TypedDict, Unpack

from pydantic import BaseModel

from ..helpers import filter_non_null
from ..mixins import ModelMixin as _ModelMixin
from ..typings import DictT  # ruff: ignore[typing-only-first-party-import]
from .other import Collation  # ruff: ignore[typing-only-first-party-import]


class _UpdateKwargs(TypedDict):
    """Kwargs used in Update model."""

    upsert: NotRequired[bool]
    multi: NotRequired[bool]
    collation: NotRequired[Collation | None]
    array_filters: NotRequired[DictT | None]
    hint: NotRequired[str | None]


# https://www.mongodb.com/docs/manual/reference/command/update/#syntax
class Update(_ModelMixin):
    """Represents a MongoDB update document."""

    def __init__(
        self,
        q: DictT,
        u: DictT,
        c: DictT | None = None,
        /,
        **kwargs: Unpack[_UpdateKwargs],
    ) -> None:
        BaseModel.__init__(self, q=q, u=u, c=c, **kwargs)

    q: DictT
    u: DictT
    c: DictT | None = None  # constants
    upsert: bool = False
    multi: bool = False
    collation: Collation | None = None
    array_filters: DictT | None = None
    hint: str | None = None

    def as_bulk_write_op(self) -> DictT:
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
            "upsert": self.upsert,
        })


class _DeleteKwargs(TypedDict):
    """Kwargs used in Delete model."""

    limit: int
    collation: NotRequired[Collation | None]
    hint: NotRequired[DictT | str | None]


# https://www.mongodb.com/docs/manual/reference/command/delete/#syntax
class Delete(_ModelMixin):
    """Represents a MongoDB delete document."""

    def __init__(self, q: DictT, /, **kwargs: Unpack[_DeleteKwargs]) -> None:
        BaseModel.__init__(self, q=q, **kwargs)

    q: DictT  # query
    limit: int
    collation: Collation | None = None
    hint: DictT | str | None = None

    def as_bulk_write_op(self) -> DictT:
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
