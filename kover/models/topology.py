"""Normalized server topology descriptions used by selection policies."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from .address import Address  # ruff: ignore[typing-only-first-party-import]
from .hello import HelloResult  # ruff: ignore[typing-only-first-party-import]


class ServerType(StrEnum):
    """Server roles relevant to initial discovery."""

    STANDALONE = "Standalone"
    MONGOS = "Mongos"
    RS_PRIMARY = "RSPrimary"
    RS_SECONDARY = "RSSecondary"
    RS_ARBITER = "RSArbiter"
    RS_OTHER = "RSOther"
    RS_GHOST = "RSGhost"


class ServerDescription(BaseModel):
    """An address and its most recently observed hello response."""

    address: Address
    hello: HelloResult
    round_trip_time: float = 0.0
    updated_at: float = 0.0

    @property
    def server_type(self) -> ServerType:
        """Classify the server using hello role precedence."""
        hello = self.hello
        if hello.msg == "isdbgrid":
            return ServerType.MONGOS

        if hello.is_replica_set:
            return ServerType.RS_GHOST

        if hello.set_name is None:
            return ServerType.STANDALONE

        roles = (
            (hello.hidden, ServerType.RS_OTHER),
            (hello.is_primary, ServerType.RS_PRIMARY),
            (hello.secondary, ServerType.RS_SECONDARY),
            (hello.arbiter_only, ServerType.RS_ARBITER),
        )

        return next(
            (role for matches, role in roles if matches),
            ServerType.RS_OTHER,
        )

    @property
    def tags(self) -> dict[str, str]:
        """Server tag document."""
        return self.hello.tags

    @property
    def last_write_date(self) -> datetime | None:
        """Server-reported last-write timestamp."""
        value: Any = self.hello.last_write.get("lastWriteDate")
        return value if isinstance(value, datetime) else None
