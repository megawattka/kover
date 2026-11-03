"""Read preference validation and command classification."""

from __future__ import annotations

from collections.abc import Mapping  # ruff: ignore[typing-only-standard-library-import]
from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .typings import DictT

ReadPreferenceMode = Literal[
    "primary",
    "primaryPreferred",
    "secondary",
    "secondaryPreferred",
    "nearest",
]

_MODES = {
    "primary",
    "primaryPreferred",
    "secondary",
    "secondaryPreferred",
    "nearest",
}
_READ_COMMANDS = {"find", "count", "distinct", "aggregate"}
_MIN_STALENESS = 90


@dataclass(frozen=True)
class ReadPreference:
    """Read routing policy; staleness values are seconds.

    Tag sets are evaluated in order; an empty tag set matches any server.
    ``-1`` disables max staleness. Transactions require primary reads.
    """

    mode: ReadPreferenceMode = "primary"
    tag_sets: tuple[Mapping[str, str], ...] | None = None
    max_staleness_seconds: int = -1

    def __post_init__(self) -> None:
        if self.mode not in _MODES:
            raise ValueError(f"unsupported read preference mode: {self.mode}")
        staleness = self.max_staleness_seconds
        if isinstance(staleness, bool) or not isinstance(staleness, int):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError("max_staleness_seconds must be an integer")
        if staleness != -1 and staleness < _MIN_STALENESS:
            raise ValueError("max_staleness_seconds must be -1 or >= 90")
        if self.tag_sets is not None:
            if any(
                not isinstance(key, str) or not isinstance(value, str)  # pyright: ignore[reportUnnecessaryIsInstance]
                for tags in self.tag_sets
                for key, value in tags.items()
            ):
                raise ValueError(
                    "tag_sets must contain string-to-string mappings",
                )
            object.__setattr__(
                self,
                "tag_sets",
                tuple(MappingProxyType(dict(tags)) for tags in self.tag_sets),
            )
        if self.mode == "primary" and (
            staleness != -1 or any(self.tag_sets or ())
        ):
            raise ValueError("primary does not support tags or max staleness")

    def to_dict(self) -> DictT:
        """Return a fresh wire-protocol read preference document."""
        result: DictT = {"mode": self.mode}
        if self.tag_sets is not None:
            result["tags"] = [dict(tags) for tags in self.tag_sets]
        if self.max_staleness_seconds != -1:
            result["maxStalenessSeconds"] = self.max_staleness_seconds
        return result


def is_read_command(command: DictT) -> bool:
    """Whether a command may use a non-primary read preference.

    Unknown/admin commands and aggregation writes conservatively use primary.

    Returns:
        True for commands that can read from a secondary.
    """
    name = next(iter(command), "")
    if name == "explain":
        return is_read_command(command["explain"])
    if name == "aggregate":
        return not any(
            "$out" in stage or "$merge" in stage
            for stage in command.get("pipeline", [])
        )
    if name == "mapReduce":
        return command.get("out") == {"inline": 1}
    return name in _READ_COMMANDS


def validate_threshold(seconds: float) -> None:
    """Validate a nonnegative, finite latency window in seconds.

    Raises:
        ValueError: If the threshold is negative or not finite.
    """
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("local_threshold must be finite and >= 0")
