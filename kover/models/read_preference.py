"""Read preference validation and command classification."""

from __future__ import annotations

from collections.abc import Mapping  # ruff: ignore[typing-only-standard-library-import]
from typing import Any, Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    model_validator,
)

ReadPreferenceMode = Literal[
    "primary",
    "primaryPreferred",
    "secondary",
    "secondaryPreferred",
    "nearest",
]

_MODES: Final[set[str]] = {
    "primary",
    "primaryPreferred",
    "secondary",
    "secondaryPreferred",
    "nearest",
}
_MIN_STALENESS: Final[int] = 90


class ReadPreference(BaseModel):
    """Read routing policy; staleness values are seconds.

    Tag sets are evaluated in order; an empty tag set matches any server.
    ``-1`` disables max staleness. Transactions require primary reads.
    """

    model_config = ConfigDict(serialize_by_alias=True)

    mode: ReadPreferenceMode = "primary"
    tag_sets: tuple[Mapping[str, str], ...] | None = Field(
        default=None,
        serialization_alias="tags",
        exclude_if=lambda value: value is None,
    )
    max_staleness_seconds: int = Field(
        default=-1,
        serialization_alias="maxStalenessSeconds",
        exclude_if=lambda value: value == -1,
    )

    @field_serializer("tag_sets")
    @staticmethod
    def _serialize_tag_sets(
        value: tuple[Mapping[str, str], ...] | None,
    ) -> list[dict[str, str]] | None:
        return None if value is None else [dict(tags) for tags in value]

    @model_validator(mode="after")
    def _validate_read_preference(self) -> Self:
        if self.mode not in _MODES:
            raise ValueError(f"unsupported read preference mode: {self.mode}")

        if (
            self.max_staleness_seconds != -1
            and self.max_staleness_seconds < _MIN_STALENESS
        ):
            raise ValueError("max_staleness_seconds must be -1 or >= 90")

        if self.mode == "primary" and (
            self.max_staleness_seconds != -1 or self.tag_sets
        ):
            raise ValueError("primary does not support tags or max staleness")

        return self

    def to_dict(self) -> dict[str, Any]:
        """Return a fresh wire-protocol read preference document."""
        return self.model_dump()
