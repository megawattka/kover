from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from kover.models.address import Address
from kover.models.hello import HelloResult
from kover.models.options import DiscoveryOptions
from kover.models.read_preference import ReadPreference
from kover.models.topology import ServerDescription, ServerType
from kover.topology.discovery import ServerDiscovery
from kover.topology.protocols import IServerDiscovery
from kover.topology.selector import (
    ServerSelectionError,
    ServerSelector,
    eligible_servers,
)


def server(
    host: str,
    *,
    primary: bool = False,
    mongos: bool = False,
    write_time: int = 1000,
    updated_at: float = 100.0,
    rtt: float = 0.001,
    tags: dict[str, str] | None = None,
    include_last_write: bool = True,
    hosts: list[str] | None = None,
) -> ServerDescription:
    hello = HelloResult(
        isWritablePrimary=primary,
        setName="rs" if not mongos else None,
        secondary=not primary and not mongos,
        msg="isdbgrid" if mongos else None,
        tags=tags or {},
        lastWrite=(
            {"lastWriteDate": datetime.fromtimestamp(write_time, UTC)}
            if include_last_write
            else {}
        ),
        hosts=hosts or [],
    )
    return ServerDescription(
        address=Address(host=host),
        hello=hello,
        round_trip_time=rtt,
        updated_at=updated_at,
    )


def selector(
    descriptions: list[ServerDescription],
    *,
    direct: bool = False,
    local_threshold: float = 0.015,
    discovery: AsyncMock | None = None,
) -> ServerSelector:
    return ServerSelector(
        discovery or AsyncMock(spec=IServerDiscovery),
        DiscoveryOptions(
            direct_connection=direct,
            local_threshold=local_threshold,
            server_selection_timeout=0.05,
        ),
        descriptions,
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("primary", ["p"]),
        ("primaryPreferred", ["p"]),
        ("secondary", ["s"]),
        ("secondaryPreferred", ["s"]),
        ("nearest", ["p", "s"]),
    ],
)
def test_read_preference_modes(mode: str, expected: list[str]) -> None:
    descriptions = [server("p", primary=True), server("s")]
    assert [
        item.address.host
        for item in eligible_servers(
            descriptions,
            ReadPreference(mode=mode),  # pyright: ignore[reportArgumentType]
        )
    ] == expected


def test_preferred_fallback_and_tag_order() -> None:
    primary = server("p", primary=True, hosts=["p", "s"])
    west = server("w", tags={"dc": "west"})
    servers = [primary, west]
    assert eligible_servers(
        servers,
        ReadPreference(mode="primaryPreferred", tag_sets=({"dc": "west"},)),
    ) == [primary]
    assert eligible_servers(
        servers,
        ReadPreference(mode="secondaryPreferred", tag_sets=({"dc": "east"},)),
    ) == [primary]
    assert eligible_servers(
        servers,
        ReadPreference(
            mode="secondary",
            tag_sets=({"dc": "east"}, {"dc": "west"}),
        ),
    ) == [west]


def test_staleness_and_missing_last_write() -> None:
    primary = server("p", primary=True, write_time=1000, updated_at=100)
    fresh = server("fresh", write_time=990, updated_at=100)
    stale = server("stale", write_time=800, updated_at=100)
    missing = server("missing", include_last_write=False)
    selected = eligible_servers(
        [primary, fresh, stale, missing],
        ReadPreference(mode="secondary", max_staleness_seconds=90),
    )
    assert selected == [fresh]


async def test_latency_window_and_random_choice() -> None:
    fast = server("fast", rtt=0.001)
    near = server("near", rtt=0.010)
    slow = server("slow", rtt=0.100)
    instance = selector([fast, near, slow], local_threshold=0.015)
    with patch("kover.topology.selector.choice", return_value=near) as choose:
        assert (
            await instance.select(ReadPreference(mode="nearest"))
            == near.address
        )
    choose.assert_called_once_with([fast, near])


async def test_mongos_is_selected_and_direct_connection_ignores_role() -> None:
    router = server("router", mongos=True, rtt=0.01)
    primary = server("p", primary=True, rtt=0.001)
    mongos_selector = selector([primary, router])
    assert await mongos_selector.select(ReadPreference()) == router.address

    direct = selector([server("secondary")], direct=True)
    assert await direct.select(ReadPreference()) == Address(host="secondary")


async def test_direct_discovers_secondary_for_primary_preference() -> None:
    secondary = server("secondary")
    discovery = AsyncMock(spec=IServerDiscovery)
    discovery.scan.return_value = [secondary]
    direct = selector([], direct=True, discovery=discovery)

    assert await direct.select(ReadPreference()) == secondary.address
    discovery.scan.assert_awaited_once()


async def test_cache_refresh_and_atomic_snapshot_replacement() -> None:
    secondary = server("s")
    replacement = server("p", primary=True)
    discovery = AsyncMock(spec=IServerDiscovery)
    discovery.scan.return_value = [replacement]
    instance = selector([secondary], discovery=discovery)

    assert (
        await instance.select(ReadPreference(mode="secondary"))
        == secondary.address
    )
    assert (
        await instance.select(ReadPreference(mode="primary"))
        == replacement.address
    )
    discovery.scan.assert_awaited_once()
    assert instance.description(replacement.address) == replacement


async def test_empty_cache_discovers_primary_and_reuses_snapshot() -> None:
    primary = server("p", primary=True)
    discovery = AsyncMock(spec=IServerDiscovery)
    discovery.scan.return_value = [primary]
    instance = selector([], discovery=discovery)

    assert await instance.select(ReadPreference()) == primary.address
    assert instance.description(primary.address) == primary
    assert await instance.select(ReadPreference()) == primary.address
    discovery.scan.assert_awaited_once()


async def test_selection_deadline_bounds_waiting_for_lock() -> None:
    instance = selector([])
    await instance._lock.acquire()  # pyright: ignore[reportPrivateUsage] # ruff: ignore[private-member-access]
    try:
        deadline = asyncio.get_running_loop().time() + 0.005
        with pytest.raises(ServerSelectionError, match="deadline"):
            await instance.select(ReadPreference(), deadline=deadline)
    finally:
        instance._lock.release()  # pyright: ignore[reportPrivateUsage] # ruff: ignore[private-member-access]


async def test_no_candidates_without_discovery_fails_by_deadline() -> None:
    discovery = AsyncMock(spec=IServerDiscovery)
    discovery.scan.return_value = []
    instance = selector([], discovery=discovery)
    with pytest.raises(ServerSelectionError, match="deadline"):
        await instance.select(ReadPreference())


def test_role_classification_and_unknown_description() -> None:
    instance = selector([server("p", primary=True)])
    assert (
        instance.description(Address(host="p")).server_type
        is ServerType.RS_PRIMARY
    )
    with pytest.raises(ServerSelectionError, match="no known description"):
        instance.description(Address(host="unknown"))


async def test_discovery_retains_members_across_preferences() -> None:
    primary = server("p", primary=True, hosts=["p", "s"])
    secondary = server("s")
    probe = AsyncMock()
    probe.probe.side_effect = [primary, secondary]
    discovery = ServerDiscovery(
        [primary.address],
        options=DiscoveryOptions(replica_set="rs"),
        probe=probe,
    )

    observed = await discovery.scan()
    assert {description.address for description in observed} == {  # pyright: ignore[reportUnhashable]
        primary.address,  # pyright: ignore[reportUnhashable]
        secondary.address,  # pyright: ignore[reportUnhashable]
    }
    assert probe.probe.await_count == 2
