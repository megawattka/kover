from __future__ import annotations

# pyright: reportPrivateUsage=false
import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from kover import (
    Kover,
    PoolClosedError,
    PoolTimeoutError,
    ReadPreference,
    ServerSelectionError,
)
from kover.enums import TxnState
from kover.models.network import Address
from kover.network.discovery import DiscoveryOptions, ServerDescription
from kover.network.pool import CommandReply, ConnectionPool
from kover.network.selection import candidates, choose
from kover.read_preferences import is_read_command
from kover.session import Session
from kover.uri_parser import parse_uri

from .test_cursor_extra import make_cursor
from .test_discovery import discovery, hello

if TYPE_CHECKING:
    from kover.read_preferences import ReadPreferenceMode
    from kover.typings import DictT


def member(
    host: str,
    *,
    primary: bool = False,
    write: int = 1000,
    updated: float = 100,
    rtt: float = 0.001,
    tags: dict[str, str] | None = None,
) -> ServerDescription:
    return ServerDescription(
        Address(host=host),
        hello(
            setName="rs",
            isWritablePrimary=primary,
            secondary=not primary,
            lastWrite={"lastWriteDate": datetime.fromtimestamp(write, UTC)},
            tags=tags or {},
        ),
        rtt,
        updated,
    )


@pytest.mark.parametrize(
    ("mode", "expected", "fallback"),
    [
        ("primary", ["p"], []),
        ("primaryPreferred", ["p"], ["s"]),
        ("secondary", ["s"], ["s"]),
        ("secondaryPreferred", ["s"], ["s"]),
        ("nearest", ["p", "s"], ["s"]),
    ],
)
def test_modes(
    mode: ReadPreferenceMode,
    expected: list[str],
    fallback: list[str],
) -> None:
    servers = [member("p", primary=True), member("s")]
    preference = ReadPreference(mode)
    assert [
        s.address.host for s in candidates(servers, preference)
    ] == expected
    assert [
        s.address.host for s in candidates(servers[1:], preference)
    ] == fallback


def test_tags_order_and_preferred_fallback() -> None:
    primary = member("p", primary=True)
    east = member("e", tags={"dc": "east", "rack": "a"})
    west = member("w", tags={"dc": "west"})
    servers = [primary, east, west]
    assert candidates(
        servers,
        ReadPreference(
            "secondary",
            ({"dc": "missing"}, {"dc": "east"}, {}),
        ),
    ) == [east]
    assert (
        candidates(
            servers,
            ReadPreference(
                "secondary",
                ({"dc": "east", "rack": "missing"},),
            ),
        )
        == []
    )
    assert candidates(
        servers,
        ReadPreference(
            "secondaryPreferred",
            ({"dc": "missing"},),
        ),
    ) == [primary]
    assert candidates(
        servers,
        ReadPreference(
            "primaryPreferred",
            ({"dc": "missing"},),
        ),
    ) == [primary]
    assert candidates(servers, ReadPreference("nearest", ({},))) == servers


@pytest.mark.parametrize("with_primary", [True, False])
def test_staleness_before_tags_and_latency(*, with_primary: bool) -> None:
    primary = member("p", primary=True)
    fresh = member("fresh", write=990, tags={"dc": "fresh"})
    boundary = member("boundary", write=910, updated=90)
    stale = member("stale", write=800, tags={"dc": "stale"})
    servers = [fresh, boundary, stale]
    if with_primary:
        servers.insert(0, primary)
    assert candidates(
        servers,
        ReadPreference(
            "secondary",
            ({"dc": "stale"}, {}),
            90,
        ),
    ) == [fresh, boundary]
    assert candidates(
        servers,
        ReadPreference(
            "secondaryPreferred",
            ({"dc": "stale"},),
            90,
        ),
    ) == ([primary] if with_primary else [])


def test_missing_last_write_is_ineligible_and_nearest_keeps_primary() -> None:
    primary = member("p", primary=True)
    missing = ServerDescription(
        Address(host="s"),
        hello(
            setName="rs",
            secondary=True,
        ),
    )
    assert candidates(
        [primary, missing],
        ReadPreference(
            "nearest",
            max_staleness_seconds=90,
        ),
    ) == [primary]
    assert (
        candidates(
            [missing],
            ReadPreference(
                "secondary",
                max_staleness_seconds=90,
            ),
        )
        == []
    )


def test_latency_window() -> None:
    fast, near, slow = (
        member("fast"),
        member("near", rtt=0.010),
        member(
            "slow",
            rtt=0.100,
        ),
    )
    with patch("kover.network.selection.random.choice") as random_choice:
        random_choice.return_value = near
        assert choose([fast, near, slow], 0.015) is near
        random_choice.assert_called_once_with([fast, near])
    assert choose([fast, slow], 0) is fast
    assert choose([], 0.015) is None


@pytest.mark.parametrize(
    "settings",
    [
        {"mode": "invalid"},
        {"max_staleness_seconds": 90},
        {"tag_sets": ({"dc": "x"},)},
        {"mode": "secondary", "max_staleness_seconds": 89},
        {"mode": "secondary", "max_staleness_seconds": -2},
        {"mode": "secondary", "tag_sets": ({"dc": 1},)},
    ],
)
def test_validation(settings: DictT) -> None:
    with pytest.raises(
        ValueError, match=r"read preference|staleness|tags|tag_sets",
    ):
        ReadPreference(**settings)


def test_policy_copies_tags_and_wire_documents() -> None:
    tags = {"dc": "east"}
    preference = ReadPreference("secondary", (tags,), 90)
    tags["dc"] = "west"
    wire = preference.to_dict()
    wire["tags"][0]["dc"] = "changed"
    assert preference.to_dict() == {
        "mode": "secondary",
        "tags": [{"dc": "east"}],
        "maxStalenessSeconds": 90,
    }
    assert ReadPreference("secondary", ()).to_dict()["tags"] == []
    for value in (True, 90.5):
        with pytest.raises(TypeError):
            ReadPreference("secondary", max_staleness_seconds=value)  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(
    "command",
    [
        {"find": "c"},
        {"count": "c"},
        {"distinct": "c"},
        {"aggregate": "c", "pipeline": [{"$match": {"x": 1}}]},
        {"mapReduce": "c", "out": {"inline": 1}},
        {"explain": {"find": "c"}},
    ],
)
def test_read_classification(command: DictT) -> None:
    assert is_read_command(command)


@pytest.mark.parametrize(
    "command",
    [
        {"insert": "c"},
        {"update": "c"},
        {"delete": "c"},
        {"findAndModify": "c"},
        {"bulkWrite": 1},
        {"listCollections": 1},
        {"getMore": 1},
        {"killCursors": "c"},
        {"unknown": 1},
        {"aggregate": "c", "pipeline": [{"$out": "output"}]},
        {"aggregate": "c", "pipeline": [{"$merge": "output"}]},
        {"explain": {"update": "c"}},
    ],
)
def test_primary_classification(command: DictT) -> None:
    assert not is_read_command(command)


async def routed_pool(
    preference: ReadPreference,
) -> ConnectionPool:
    selector, _ = discovery(
        {
            "p": hello(setName="rs", isWritablePrimary=True, hosts=["p", "s"]),
            "s": hello(setName="rs", secondary=True, hosts=["p", "s"]),
        },
        ["s"],
        read_preference=preference,
    )
    with patch("kover.network.pool.ServerDiscovery", return_value=selector):
        return await ConnectionPool.discover(
            [Address(host="s")],
            options=DiscoveryOptions(
                read_preference=preference,
            ),
        )


async def test_per_command_routing_and_input_immutability() -> None:
    pool = await routed_pool(ReadPreference("secondary"))
    seen: list[tuple[str, DictT]] = []

    async def execute(self: ConnectionPool, doc: DictT, **_: object) -> DictT:
        await asyncio.sleep(0)
        seen.append((self.address.host, doc))
        return {"ok": 1}

    original = {"find": "c"}
    with patch.object(ConnectionPool, "_request_local", execute):
        response = await pool.request(original)
        assert isinstance(response, CommandReply)
        assert response.server_address == Address(host="s")
        await pool.request(
            {"insert": "c", "$readPreference": {"mode": "nearest"}},
        )
        await pool.request(original, read_preference=ReadPreference())
        await pool.request({"aggregate": "c", "pipeline": [{"$out": "o"}]})
    assert original == {"find": "c"}
    assert [host for host, _ in seen] == ["s", "p", "p", "p"]
    assert seen[0][1]["$readPreference"] == {"mode": "secondary"}
    assert all("$readPreference" not in command for _, command in seen[1:])
    await pool.close()


@pytest.mark.parametrize("finish", ["commit_transaction", "abort_transaction"])
async def test_transaction_primary_restriction_override_and_pin(
    finish: str,
) -> None:
    pool = await routed_pool(ReadPreference("secondary"))
    client = Kover(pool=pool)
    session = Session({"id": "session"}, client)
    session.start_transaction()
    with patch.object(
        ConnectionPool,
        "_request_local",
        new_callable=AsyncMock,
    ) as execute:
        execute.return_value = {"ok": 1}
        with pytest.raises(ValueError, match="transaction reads"):
            await client.request({"find": "c"}, session=session)
        execute.assert_not_awaited()
        assert session.state is TxnState.STARTING
        assert session.pinned_server_address is None
        await client.request(
            {"find": "c"},
            session=session,
            read_preference=ReadPreference(),
        )
        assert session.pinned_server_address == Address(host="p")
        assert execute.await_args is not None
        assert "$readPreference" not in execute.await_args.args[0]
        await getattr(session, finish)()
        assert session.pinned_server_address is None
    await client.close()


async def test_secondary_only_does_not_route_writes_to_secondary() -> None:
    selector, _ = discovery(
        {"s": hello(setName="rs", secondary=True)},
        ["s"],
        read_preference=ReadPreference("secondary"),
    )
    with patch("kover.network.pool.ServerDiscovery", return_value=selector):
        pool = await ConnectionPool.discover(
            [Address(host="s")],
            options=DiscoveryOptions(
                read_preference=ReadPreference("secondary"),
            ),
        )
    with patch.object(
        ConnectionPool,
        "_request_local",
        new_callable=AsyncMock,
    ) as execute:
        with pytest.raises(ServerSelectionError):
            await pool.request(
                {"insert": "c"},
                deadline=asyncio.get_running_loop().time() + 0.01,
            )
        execute.assert_not_awaited()
    await pool.close()


@pytest.mark.parametrize(
    "mode",
    [
        "primary",
        "primaryPreferred",
        "secondary",
        "secondaryPreferred",
        "nearest",
    ],
)
async def test_uri_preferences(mode: ReadPreferenceMode) -> None:
    parsed = await parse_uri(
        f"mongodb://s/?readPreference={mode}&localThresholdMS=17",
    )
    with patch.object(
        ConnectionPool,
        "discover",
        new_callable=AsyncMock,
    ) as discover_pool:
        await ConnectionPool.from_parsed_uri(parsed)
    assert discover_pool.await_args is not None
    options = discover_pool.await_args.kwargs["options"]
    assert options.read_preference == ReadPreference(mode)
    assert options.local_threshold == pytest.approx(0.017)


async def test_uri_tags_and_staleness() -> None:
    parsed = await parse_uri(
        "mongodb://s/?readPreference=secondary&readPreferenceTags=dc:east"
        "&readPreferenceTags=&maxStalenessSeconds=90",
    )
    with patch.object(
        ConnectionPool,
        "discover",
        new_callable=AsyncMock,
    ) as discover_pool:
        await ConnectionPool.from_parsed_uri(parsed)
    assert discover_pool.await_args is not None
    assert discover_pool.await_args.kwargs[
        "options"
    ].read_preference == ReadPreference(
        "secondary",
        ({"dc": "east"}, {}),
        90,
    )


async def test_cursor_affinity_and_override() -> None:
    source = Address(host="secondary")
    command = AsyncMock(
        side_effect=[
            CommandReply(
                {"cursor": {"id": 42, "firstBatch": [{"x": 1}]}},
                source,
            ),
            CommandReply(
                {"cursor": {"id": 42, "nextBatch": [{"x": 2}]}},
                source,
            ),
            {"ok": 1},
        ],
    )
    preference = ReadPreference("secondary")
    cursor = make_cursor(command, {"find": "items"}).read_preference(
        preference,
    )
    assert await anext(cursor) == {"x": 1}
    with pytest.raises(RuntimeError, match="already started"):
        cursor.read_preference(ReadPreference())
    assert await anext(cursor) == {"x": 2}
    await cursor.close()
    assert command.await_args_list[0].kwargs == {
        "session": None,
        "read_preference": preference,
    }
    assert all(
        call.kwargs["server_address"] == source
        for call in command.await_args_list[1:]
    )
    assert "getMore" in command.await_args_list[1].args[0]
    assert "killCursors" in command.await_args_list[2].args[0]


@pytest.mark.parametrize("role", ["mongos", "standalone", "secondary"])
async def test_wire_metadata_by_topology(role: str) -> None:
    response = {
        "mongos": hello(msg="isdbgrid"),
        "standalone": hello(isWritablePrimary=True),
        "secondary": hello(setName="rs", secondary=True),
    }[role]
    selector, _ = discovery({"s": response}, ["s"], direct_connection=True)
    with patch("kover.network.pool.ServerDiscovery", return_value=selector):
        pool = await ConnectionPool.discover([Address(host="s")])
    with patch.object(
        ConnectionPool,
        "_request_local",
        new_callable=AsyncMock,
    ) as execute:
        execute.return_value = {"ok": 1}
        await pool.request({"find": "c"})
        assert execute.await_args is not None
        metadata = execute.await_args.args[0].get("$readPreference")
        assert metadata == (
            {"mode": "primaryPreferred"} if role == "secondary" else None
        )
        await pool.request(
            {"find": "c"},
            read_preference=ReadPreference("nearest"),
        )
        assert execute.await_args.args[0].get("$readPreference") == (
            None if role == "standalone" else {"mode": "nearest"}
        )
        await pool.request({"insert": "c"})
        assert "$readPreference" not in execute.await_args.args[0]
    await pool.close()


@pytest.mark.parametrize(
    ("mode", "healthy_role", "healthy_host"),
    [
        ("primaryPreferred", "primary", "p"),
        ("primaryPreferred", "secondary", "s"),
        ("secondaryPreferred", "primary", "p"),
        ("secondary", "secondary", "s"),
        ("nearest", "secondary", "s"),
    ],
)
async def test_slow_member_does_not_prevent_selection(
    mode: ReadPreferenceMode, healthy_role: str, healthy_host: str,
) -> None:
    selector, probes = discovery(
        {
            "slow": hello(setName="rs", secondary=True),
            healthy_host: hello(
                setName="rs", isWritablePrimary=healthy_role == "primary",
                secondary=healthy_role == "secondary",
            ),
        },
        ["slow", healthy_host], read_preference=ReadPreference(mode),
        connect_timeout=None,
    )

    async def hang() -> None:
        await asyncio.Event().wait()

    probes["slow"].connect.side_effect = hang
    async with asyncio.timeout(0.5):
        assert await selector.select() == Address(host=healthy_host)
    probes["slow"].abort.assert_called_once()
    probes["slow"].close.assert_awaited_once()


async def test_primary_preferred_does_not_wait_for_slow_member() -> None:
    selector, probes = discovery(
        {
            "p": hello(setName="rs", isWritablePrimary=True),
            "s": hello(setName="rs", secondary=True),
        },
        ["p", "s"], read_preference=ReadPreference("primaryPreferred"),
        connect_timeout=None,
    )

    async def hang() -> None:
        await asyncio.Event().wait()

    probes["s"].connect.side_effect = hang
    async with asyncio.timeout(0.02):
        assert await selector.select() == Address(host="p")
    probes["s"].close.assert_awaited_once()


async def test_selection_lock_deadline_and_cached_reads_bypass_lock() -> None:
    pool = await routed_pool(ReadPreference())
    await pool._selection_lock.acquire()  # ruff: ignore[private-member-access]
    try:
        with patch.object(
            ConnectionPool, "_request_local", new_callable=AsyncMock,
        ) as execute:
            execute.return_value = {"ok": 1}
            # A cached primary must not wait for unrelated discovery.
            async with asyncio.timeout(0.1):
                await pool.request({"find": "c"})
            with pytest.raises(PoolTimeoutError, match="selection deadline"):
                await pool.request(
                    {"find": "c"}, read_preference=ReadPreference(
                        "secondary", ({"dc": "missing"},),
                    ),
                    deadline=asyncio.get_running_loop().time() + 0.01,
                )
            assert execute.await_count == 1
    finally:
        pool._selection_lock.release()  # ruff: ignore[private-member-access]
        await pool.close()


async def test_pinned_cursor_survives_unsuitable_rescan() -> None:
    selector, probes = discovery(
        {"s": hello(setName="rs", secondary=True)}, ["s"],
        read_preference=ReadPreference("secondary"),
    )
    with patch("kover.network.pool.ServerDiscovery", return_value=selector):
        pool = await ConnectionPool.discover([Address(host="s")])
    probes["s"].hello.side_effect = OSError("unreachable")
    with patch.object(
        ConnectionPool, "_request_local", new_callable=AsyncMock,
    ) as execute:
        execute.return_value = {"ok": 1}
        with pytest.raises(ServerSelectionError):
            await pool.request(
                {"insert": "c"},
                deadline=asyncio.get_running_loop().time() + 0.01,
            )
        await pool.request(
            {"getMore": 42, "collection": "c"},
            server_address=Address(host="s"),
        )
        execute.assert_awaited_once()
        description = selector.description(Address(host="s"))
        assert description.server_type == "RSSecondary"
    await pool.close()


async def test_explicit_address_cannot_route_writes_to_secondary() -> None:
    pool = await routed_pool(ReadPreference("secondary"))
    seen: list[Address] = []

    async def execute(self: ConnectionPool, _: DictT, **__: object) -> DictT:
        await asyncio.sleep(0)
        seen.append(self.address)
        return {"ok": 1}

    with patch.object(ConnectionPool, "_request_local", execute):
        await pool.request({"insert": "c"}, server_address=Address(host="s"))
    assert seen == [Address(host="p")]
    child = pool._pool_for(Address(host="p"))  # ruff: ignore[private-member-access]
    assert child._max_pool_size == pool._max_pool_size  # ruff: ignore[private-member-access]
    await pool.close()
    assert child.closed
    with pytest.raises(PoolClosedError, match="closed"):
        await pool.request({"find": "c"})


async def test_programmatic_client_preference() -> None:
    preference = ReadPreference("nearest", ({"dc": "east"},), 100)
    with patch.object(
        ConnectionPool, "discover", new_callable=AsyncMock,
    ) as discover_pool:
        await Kover.make_client(
            "seed", read_preference=preference, local_threshold=0.02,
        )
    assert discover_pool.await_args is not None
    options = discover_pool.await_args.kwargs["options"]
    assert options.read_preference == preference
    assert options.local_threshold == pytest.approx(0.02)
