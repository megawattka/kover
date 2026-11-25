"""Kover topology version."""

from __future__ import annotations

from typing import Any

from elune import Int64, ObjectId  # ruff: ignore[typing-only-third-party-import]
from pydantic import BaseModel, ConfigDict, Field


class TopologyVersion(BaseModel):
    """The process identity and change counter used by awaitable hello."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    process_id: ObjectId = Field(alias="processId")
    counter: int

    def document(self) -> dict[str, Any]:
        """Return the wire document, preserving the BSON int64 counter."""
        return {"processId": self.process_id, "counter": Int64(self.counter)}

    def compare(self, previous: TopologyVersion | None) -> int:
        """Compare counters from one process; otherwise treat this as new.

        Returns:
            A negative, zero, or positive comparison result.
        """
        if previous is None or self.process_id != previous.process_id:
            return 1
        return (self.counter > previous.counter) - (
            self.counter < previous.counter
        )
