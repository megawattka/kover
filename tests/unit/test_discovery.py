from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from kover import AuthCredentials, Kover, ServerSelectionError
from kover.models import HelloResult
from kover.models.network import Address
from kover.network.connection import Connection
from kover.network.discovery import (
    DiscoveryOptions,
    ServerDescription,
    ServerDiscovery,
    ServerType,
)
from kover.network.pool import ConnectionPool
from kover.uri_parser import parse_uri

if TYPE_CHECKING:
    from kover.typings import DictT


def hello(**fields: object) -> HelloResult:
    return HelloResult.model_validate(
        {
            "localTime": datetime.now(UTC),
            "connectionId": 1,
            "isWritablePrimary": False,
            **fields,
        },
    )


def probe(response: HelloResult | BaseException) -> MagicMock:
    connection = MagicMock(spec=Connection)
    if isinstance(response, BaseException):
        connection.hello.side_effect = response
    else:
        connection.hello.return_value = response
    return connection


def discovery(
    responses: dict[str, HelloResult | BaseException],
    seeds: list[str],
    **options: object,
) -> tuple[ServerDiscovery, dict[str, MagicMock]]:
    probes = {host: probe(response) for host, response in responses.items()}

    def factory(address: Address) -> Connection:
        return probes[address.host]

    settings = DiscoveryOptions(
        server_selection_timeout=0.04,
        **options,  # pyright: ignore[reportArgumentType]
    )
    return ServerDiscovery(
        [Address(host=seed) for seed in seeds],
        factory,
        options=settings,
    ), probes


@pytest.mark.parametrize(
    ("fields", "role"),
    [
        ({"isWritablePrimary": True}, ServerType.STANDALONE),
        ({"msg": "isdbgrid"}, ServerType.MONGOS),
        ({"isreplicaset": True}, ServerType.RS_GHOST),
        ({"setName": "rs", "isWritablePrimary": True}, ServerType.RS_PRIMARY),
        ({"setName": "rs", "secondary": True}, ServerType.RS_SECONDARY),
        ({"setName": "rs", "arbiterOnly": True}, ServerType.RS_ARBITER),
        (
            {"setName": "rs", "hidden": True, "secondary": True},
            ServerType.RS_OTHER,
        ),
        ({"setName": "rs"}, ServerType.RS_OTHER),
    ],
)
def test_hello_role_classification(fields: DictT, role: ServerType) -> None:
    description = ServerDescription(Address(host="seed"), hello(**fields))
    assert description.server_type is role


@pytest.mark.parametrize("error", [
    OSError("offline"), asyncio.IncompleteReadError(b"", 16),
])
async def test_dead_seed_does_not_hide_primary_in_seed_list(
    error: BaseException,
) -> None:
    selector, probes = discovery(
        {
            "dead": error,
            "primary": hello(setName="rs", isWritablePrimary=True),
        },
        ["dead", "primary"],
        replica_set="rs",
    )
    assert await selector.select() == Address(host="primary")
    for connection in probes.values():
        connection.abort.assert_called_once()
        connection.close.assert_awaited_once()


async def test_slow_seed_does_not_block_healthy_seed() -> None:
    selector, probes = discovery(
        {
            "slow": hello(),
            "router": hello(msg="isdbgrid"),
        },
        ["slow", "router"],
        connect_timeout=None,
    )
    entered = asyncio.Event()

    async def hang() -> None:
        entered.set()
        await asyncio.Event().wait()

    probes["slow"].connect.side_effect = hang
    assert await selector.select() == Address(host="router")
    assert entered.is_set()
    probes["slow"].close.assert_awaited_once()


async def test_selection_retries_until_primary_is_available() -> None:
    connection = probe(hello())
    connection.hello.side_effect = [
        hello(setName="rs", secondary=True),
        hello(setName="rs", isWritablePrimary=True),
    ]
    selector = ServerDiscovery(
        [Address(host="seed")], MagicMock(return_value=connection),
        options=DiscoveryOptions(server_selection_timeout=1.0),
    )
    assert await selector.select() == Address(host="seed")
    assert connection.hello.await_count == 2
    assert connection.close.await_count == 2


async def test_probe_timeout_is_reported_before_selection_deadline() -> None:
    selector, probes = discovery(
        {"seed": hello()}, ["seed"], connect_timeout=0.005,
    )

    async def hang(*_args: object) -> None:
        await asyncio.Event().wait()

    probes["seed"].hello.side_effect = hang
    with pytest.raises(ServerSelectionError, match="TimeoutError"):
        await asyncio.wait_for(selector.select(), 0.5)
    probes["seed"].close.assert_awaited_once()


@pytest.mark.parametrize(
    "source", ["hosts", "passives", "arbiters", "primary"],
)
async def test_discovers_and_verifies_advertised_primary(source: str) -> None:
    advertised: DictT = {
        source: "primary" if source == "primary" else ["primary"],
    }
    selector, probes = discovery(
        {
            "secondary": hello(setName="rs", secondary=True, **advertised),
            "primary": hello(setName="rs", isWritablePrimary=True),
        },
        ["secondary"],
        replica_set="rs",
    )
    assert await selector.select() == Address(host="primary")
    probes["primary"].hello.assert_awaited_once()


async def test_primary_hint_is_not_trusted_without_hello() -> None:
    selector, probes = discovery(
        {
            "secondary": hello(setName="rs", secondary=True, primary="stale"),
            "stale": hello(setName="rs", secondary=True, hosts=["real"]),
            "real": hello(setName="rs", isWritablePrimary=True),
        },
        ["secondary"],
    )
    assert await selector.select() == Address(host="real")
    assert probes["stale"].hello.await_count == 1


async def test_seed_alias_is_replaced_by_verified_canonical_member() -> None:
    selector, probes = discovery({
        "alias": hello(
            setName="rs", isWritablePrimary=True, me="canonical",
            hosts=["canonical"],
        ),
        "canonical": hello(
            setName="rs", isWritablePrimary=True, me="canonical",
            hosts=["canonical"],
        ),
    }, ["alias"])
    assert await selector.select() == Address(host="canonical")
    probes["canonical"].hello.assert_awaited_once()


@pytest.mark.parametrize(
    "response",
    [
        hello(setName="wrong", isWritablePrimary=True, hosts=["injected"]),
        hello(setName="rs", hidden=True, isWritablePrimary=True),
        hello(setName="rs", arbiterOnly=True),
        hello(isreplicaset=True),
        hello(isWritablePrimary=True),
        hello(msg="isdbgrid"),
    ],
)
async def test_replica_set_constraints_reject_unsuitable_server(
    response: HelloResult,
) -> None:
    selector, probes = discovery(
        {"seed": response}, ["seed"], replica_set="rs",
    )
    with pytest.raises(ServerSelectionError, match="rs"):
        await selector.select()
    probes["seed"].close.assert_awaited_once()


@pytest.mark.parametrize(
    "response",
    [
        hello(setName="rs", secondary=True),
        hello(isreplicaset=True),
        hello(setName="rs", arbiterOnly=True),
        hello(),
    ],
)
async def test_direct_connection_accepts_any_role_without_following_hosts(
    response: HelloResult,
) -> None:
    response.hosts = ["must-not-follow"]
    selector, probes = discovery(
        {"seed": response},
        ["seed"],
        direct_connection=True,
    )
    assert await selector.select() == Address(host="seed")
    probes["seed"].hello.assert_awaited_once()


async def test_direct_connection_still_checks_replica_set_name() -> None:
    selector, _ = discovery(
        {"seed": hello(setName="other", secondary=True)},
        ["seed"],
        replica_set="rs",
        direct_connection=True,
    )
    with pytest.raises(ServerSelectionError, match="does not match"):
        await selector.select()


async def test_standalones_are_not_selected_from_multi_seed_uri() -> None:
    selector, _ = discovery({"a": hello(), "b": hello()}, ["a", "b"])
    with pytest.raises(ServerSelectionError, match="Standalone"):
        await selector.select()


async def test_cycles_and_duplicate_members_are_probed_once_per_scan() -> None:
    selector, probes = discovery(
        {
            "a": hello(setName="rs", secondary=True, hosts=["a", "b", "b"]),
            "b": hello(setName="rs", secondary=True, hosts=["a"]),
        },
        ["a", "a"],
    )
    with pytest.raises(ServerSelectionError):
        await selector.select()
    for connection in probes.values():
        connection.hello.assert_awaited_once()


async def test_ipv6_advertised_address() -> None:
    primary = probe(hello(setName="rs", isWritablePrimary=True))
    secondary = probe(
        hello(setName="rs", secondary=True, primary="[::1]:27018"),
    )
    factory = MagicMock(side_effect=[secondary, primary])
    selector = ServerDiscovery([Address(host="seed")], factory)
    assert await selector.select() == Address(host="::1", port=27018)
    assert factory.call_args.args[0] == Address(host="::1", port=27018)


async def test_malformed_advertised_address_has_selection_diagnostics() -> (
    None
):
    selector, _ = discovery(
        {
            "seed": hello(setName="rs", secondary=True, hosts=["broken:bad"]),
        },
        ["seed"],
    )
    with pytest.raises(ServerSelectionError, match="seed"):
        await selector.select()


async def test_selection_deadline_cancels_and_closes_hung_probe() -> None:
    selector, probes = discovery(
        {"seed": hello()}, ["seed"], connect_timeout=None,
    )

    async def hang() -> None:
        await asyncio.Event().wait()

    probes["seed"].connect.side_effect = hang
    with pytest.raises(ServerSelectionError):
        await asyncio.wait_for(selector.select(), 0.5)
    probes["seed"].close.assert_awaited_once()


async def test_cancellation_propagates_and_closes_probe() -> None:
    selector, probes = discovery({"seed": hello()}, ["seed"])
    entered = asyncio.Event()

    async def hang() -> None:
        entered.set()
        await asyncio.Event().wait()

    probes["seed"].connect.side_effect = hang
    task = asyncio.create_task(selector.select())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    probes["seed"].abort.assert_called_once()
    probes["seed"].close.assert_awaited_once()


async def test_probe_timeout_allows_discovery_of_new_primary() -> None:
    selector, probes = discovery(
        {
            "seed": hello(
                setName="rs", secondary=True, hosts=["hung", "primary"],
            ),
            "hung": hello(),
            "primary": hello(setName="rs", isWritablePrimary=True),
        },
        ["seed"],
        connect_timeout=0.005,
    )

    async def hang() -> None:
        await asyncio.Event().wait()

    probes["hung"].connect.side_effect = hang
    assert await selector.select() == Address(host="primary")
    probes["hung"].close.assert_awaited_once()


@pytest.mark.parametrize(
    "options",
    [
        {"server_selection_timeout": -1},
        {"server_selection_timeout": float("inf")},
        {"connect_timeout": 0},
        {"connect_timeout": float("nan")},
        {"replica_set": ""},
    ],
)
def test_invalid_discovery_options(options: DictT) -> None:
    with pytest.raises(ValueError, match="must"):
        DiscoveryOptions(**options)


@pytest.mark.parametrize("seeds", [[], [Address(host="a"), Address(host="b")]])
def test_direct_requires_exactly_one_seed(seeds: list[Address]) -> None:
    factory = MagicMock()
    with pytest.raises(ValueError, match="seed"):
        ServerDiscovery(
            seeds,
            factory,
            options=DiscoveryOptions(direct_connection=True),
        )
    factory.assert_not_called()


@pytest.mark.parametrize(
    ("uri", "database"),
    [
        ("mongodb://user:password@seed/", "admin"),
        ("mongodb://user:password@seed/data", "data"),
        ("mongodb://user:password@seed/data?authSource=auth", "auth"),
    ],
)
async def test_uri_authentication_database(uri: str, database: str) -> None:
    parsed = await parse_uri(uri)
    assert parsed.credentials is not None
    assert parsed.credentials.auth_database == database


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb://a/?loadBalanced=true",
    ],
)
async def test_unsupported_options_rejected_before_probe(uri: str) -> None:
    parsed = await parse_uri(uri)
    with patch.object(ConnectionPool, "_create_connection") as factory:
        with pytest.raises(ValueError, match="supported"):
            await ConnectionPool.from_parsed_uri(parsed)
        factory.assert_not_called()


async def test_programmatic_factory_discovers_replica_primary() -> None:
    primary = probe(hello(setName="rs", isWritablePrimary=True))
    secondary = probe(hello(setName="rs", secondary=True, primary="primary"))
    credentials = AuthCredentials(username="user", password="password")
    with patch.object(
        ConnectionPool,
        "_create_connection",
        side_effect=[secondary, primary],
    ):
        client = await Kover.make_client(
            "secondary",
            credentials=credentials,
            replica_set="rs",
            compression=["zlib"],
            application={"name": "test"},
            tls=True,
        )
    assert client.pool.address == Address(host="primary")
    primary.hello.assert_awaited_once_with(
        ["zlib"],
        credentials,
        {"name": "test"},
    )
    primary.authorize.assert_not_awaited()
    await client.close()
