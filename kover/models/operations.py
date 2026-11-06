"""Operation models, required by kover."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict, Unpack

from pydantic import BaseModel, Field

from .collation import Collation  # ruff: ignore[typing-only-first-party-import]


class _UpdateKwargs(TypedDict):
    """Kwargs used in Update model."""

    upsert: NotRequired[bool]
    multi: NotRequired[bool]
    collation: NotRequired[Collation | None]
    array_filters: NotRequired[dict[str, Any] | None]
    hint: NotRequired[str | None]


# https://www.mongodb.com/docs/manual/reference/command/update/#syntax
class Update(BaseModel):
    """Represents a MongoDB update document."""

    def __init__(
        self,
        q: dict[str, Any],
        u: dict[str, Any],
        c: dict[str, Any] | None = None,
        /,
        **kwargs: Unpack[_UpdateKwargs],
    ) -> None:
        BaseModel.__init__(self, q=q, u=u, c=c, **kwargs)

    q: dict[str, Any]
    u: dict[str, Any]
    c: dict[str, Any] | None = None
    upsert: bool = False
    multi: bool = False
    collation: Collation | None = None
    array_filters: dict[str, Any] | None = Field(
        default=None,
        serialization_alias="arrayFilters",
    )
    hint: str | None = None
    sort: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the model as a dictionary using serialization aliases."""
        return self.model_dump(by_alias=True, exclude_none=True)

    def as_bulk_write_op(self) -> dict[str, Any]:
        """Serialize This model for BulkWriteBuilder.

        Returns:
            Serialized operation.
        """
        dumped = self.model_dump(
            by_alias=True,
            exclude={"q", "u", "c"},
            exclude_none=True,
        )
        return {
            "filter": self.q,
            "updateMods": self.u,
            "constants": self.c,
            **dumped,
        }


class _DeleteKwargs(TypedDict):
    """Kwargs used in Delete model."""

    limit: int
    collation: NotRequired[Collation | None]
    hint: NotRequired[dict[str, Any] | str | None]


# https://www.mongodb.com/docs/manual/reference/command/delete/#syntax
class Delete(BaseModel):
    """Represents a MongoDB delete document."""

    def __init__(
        self,
        q: dict[str, Any],
        /,
        **kwargs: Unpack[_DeleteKwargs],
    ) -> None:
        BaseModel.__init__(self, q=q, **kwargs)

    q: dict[str, Any]
    limit: int
    collation: Collation | None = None
    hint: dict[str, Any] | str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the model as a dictionary."""
        return self.model_dump(exclude_none=True)

    def as_bulk_write_op(self) -> dict[str, Any]:
        """Serialize This model for BulkWriteBuilder.

        Returns:
            Serialized operation.
        """
        multi = self.limit != 1
        dumped = self.model_dump(
            exclude={"q", "limit"},
            exclude_none=True,
        )
        return {
            "filter": self.q,
            "multi": multi,
            **dumped,
        }
