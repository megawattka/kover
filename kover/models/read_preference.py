"""Read preference validation and command classification."""

from __future__ import annotations

from collections.abc import Mapping  # ruff: ignore[typing-only-standard-library-import]
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, model_validator

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

    mode: ReadPreferenceMode = "primary"
    tag_sets: tuple[Mapping[str, str], ...] | None = None
    max_staleness_seconds: int = -1

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
        result: dict[str, Any] = {"mode": self.mode}
        if self.tag_sets is not None:
            result["tags"] = [dict(tags) for tags in self.tag_sets]

        if self.max_staleness_seconds != -1:
            result["maxStalenessSeconds"] = self.max_staleness_seconds

        return result
