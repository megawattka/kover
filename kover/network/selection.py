"""Read preference candidate filtering over discovery snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..read_preferences import ReadPreference
    from .discovery import ServerDescription


def _last_write(server: ServerDescription) -> float | None:
    value = server.hello.last_write.get("lastWriteDate")
    if not isinstance(value, datetime):
        return None
    # Differences use server timestamps, never the client's wall clock.
    return value.replace(tzinfo=UTC).timestamp()


def _fresh(
    secondaries: list[ServerDescription],
    primary: ServerDescription | None,
    maximum: int,
) -> list[ServerDescription]:
    if maximum == -1:
        return secondaries
    writes = [_last_write(server) for server in secondaries]
    reference = _last_write(primary) if primary is not None else None
    if primary is not None and reference is None:
        return []
    latest = max((value for value in writes if value is not None), default=0)
    result: list[ServerDescription] = []
    for server, write in zip(secondaries, writes, strict=True):
        if write is None:
            continue
        if primary is not None and reference is not None:
            lag = server.updated_at - primary.updated_at + reference - write
        else:
            lag = latest - write
        # No heartbeat monitor yet: use the standard 10-second interval.
        if lag + 10 <= maximum:
            result.append(server)
    return result


def _tags(
    servers: list[ServerDescription],
    preference: ReadPreference,
) -> list[ServerDescription]:
    for tags in preference.tag_sets or ({},):
        matches = [
            server
            for server in servers
            if all(
                server.hello.tags.get(key) == value
                for key, value in tags.items()
            )
        ]
        if matches:
            return matches
    return []


def candidates(
    servers: list[ServerDescription],
    preference: ReadPreference,
) -> list[ServerDescription]:
    """Apply role, max-staleness, tag and preferred-mode fallback rules.

    Returns:
        Eligible replica set members, before the latency window is applied.
    """
    primary = next(
        (server for server in servers if server.server_type == "RSPrimary"),
        None,
    )
    primaries = [primary] if primary is not None else []
    if preference.mode == "primary":
        return primaries
    if preference.mode == "primaryPreferred" and primary is not None:
        return primaries
    secondaries = _fresh(
        [server for server in servers if server.server_type == "RSSecondary"],
        primary,
        preference.max_staleness_seconds,
    )
    if preference.mode == "nearest":
        return _tags([*primaries, *secondaries], preference)
    eligible = _tags(secondaries, preference)
    if preference.mode == "secondaryPreferred" and not eligible:
        return primaries
    return eligible


def choose(
    servers: list[ServerDescription],
    local_threshold: float,
) -> ServerDescription | None:
    """Choose randomly among servers within the fastest RTT's latency window.

    Returns:
        A selected server, or None if there are no candidates.
    """
    if not servers:
        return None
    fastest = min(server.round_trip_time for server in servers)
    return random.choice(  # ruff: ignore[suspicious-non-cryptographic-random-usage]
        [
            server
            for server in servers
            if server.round_trip_time <= fastest + local_threshold
        ],
    )
