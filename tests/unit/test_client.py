from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kover import AuthCredentials, Kover, WriteConcern
from kover.models.replset import ReplicaSetConfig
from kover.network.pool import ConnectionPool
from kover.session import Session
from kover.uri_parser import parse_uri


def client_mock() -> tuple[Kover, MagicMock]:
    pool = MagicMock(spec=ConnectionPool)
    pool.request.return_value = {"ok": 1}
    return Kover(pool=pool), pool


async def test_client_routes_requests_without_mutating_input() -> None:
    client, pool = client_mock()
    session = Session({"id": "ours"}, client)
    command = {"insert": "items"}
    assert await client.request(
        command,
        db_name="test",
        session=session,
        deadline=42,
    ) == {"ok": 1}
    assert command == {"insert": "items"}
    pool.request.assert_awaited_once_with(
        {"insert": "items", "writeConcern": {"w": "majority"}},
        db_name="test",
        session=session,
        wait_response=True,
        deadline=42,
    )


@pytest.mark.parametrize(
    "command",
    [
        "insert",
        "update",
        "delete",
        "create",
        "drop",
        "dropDatabase",
        "createIndexes",
        "dropIndexes",
        "findAndModify",
        "renameCollection",
    ],
)
async def test_write_commands_receive_default_write_concern(
    command: str,
) -> None:
    client, pool = client_mock()
    assert client.set_write_concern(w=2, j=True, wtimeout=10) is client
    await client.request({command: "items"})
    assert pool.request.await_args.args[0]["writeConcern"] == {
        "w": 2,
        "j": True,
        "wtimeout": 10,
    }


@pytest.mark.parametrize("command", ["ping", "find", "getMore", "hello"])
async def test_read_commands_do_not_receive_write_concern(
    command: str,
) -> None:
    client, pool = client_mock()
    await client.request({command: 1})
    assert pool.request.await_args.args[0] == {command: 1}


async def test_operation_override_and_command_write_concern_precedence() -> (
    None
):
    client, pool = client_mock()
    await client.request({"update": "items"}, write_concern=WriteConcern(w=2))
    assert pool.request.await_args.args[0]["writeConcern"] == {"w": 2}
    await client.request(
        {"delete": "items", "writeConcern": {"w": 3}},
        write_concern=WriteConcern(w=2),
    )
    assert pool.request.await_args.args[0]["writeConcern"] == {"w": 3}


async def test_transaction_suppresses_default_write_concern() -> None:
    client, pool = client_mock()
    session = Session({"id": "ours"}, client)
    session.start_transaction()
    await client.request({"insert": "items"}, session=session)
    assert "writeConcern" not in pool.request.await_args.args[0]


async def test_foreign_sessions_rejected_before_request() -> None:
    client, pool = client_mock()
    other, _ = client_mock()
    foreign = Session({"id": "foreign"}, other)
    with pytest.raises(ValueError, match="different client"):
        await client.request({"ping": 1}, session=foreign)
    for method in (client.refresh_sessions, client.end_sessions):
        with pytest.raises(ValueError, match="foreign session"):
            await method([foreign])
    pool.request.assert_not_awaited()


async def test_session_creation_refresh_and_end() -> None:
    client, pool = client_mock()
    pool.request.return_value = {"ok": 1, "id": {"id": "logical"}}
    session = await client.start_session()
    assert session.client is client
    assert session.document == {"id": "logical"}
    assert pool.request.await_args.args[0] == {"startSession": 1}
    await client.refresh_sessions([session])
    assert pool.request.await_args.args[0] == {
        "refreshSessions": [session.document],
    }
    await client.end_sessions([session])
    assert pool.request.await_args.args[0] == {
        "endSessions": [session.document],
    }


async def test_shutdown_is_only_a_mocked_fire_and_forget_command() -> None:
    client, pool = client_mock()
    await client.shutdown(force=True, timeout=5, comment="test")
    pool.request.assert_awaited_once_with(
        {"shutdown": 1, "force": True, "timeoutSecs": 5, "comment": "test"},
        db_name="admin",
        session=None,
        wait_response=False,
        deadline=None,
    )


async def test_context_closes_pool_and_preserves_body_exception() -> None:
    client, pool = client_mock()

    async def body() -> None:
        async with client as entered:
            assert entered is client
            raise ValueError("body")

    with pytest.raises(ValueError, match="body"):
        await body()
    pool.close.assert_awaited_once()
    assert client.pool is pool


async def test_factory_is_lazy_and_passes_network_configuration() -> None:
    credentials = AuthCredentials(username="user", password="password")
    with patch("kover.client.ConnectionPool", autospec=True) as pool_type:
        client = await Kover.make_client(
            "host",
            27018,
            credentials=credentials,
            compression=["zlib"],
            tls=True,
            application={"name": "test"},
            w=2,
            max_pool_size=3,
        )
        pool_type.assert_called_once_with(
            "host",
            27018,
            credentials=credentials,
            loop=None,
            compression=["zlib"],
            tls=True,
            application={"name": "test"},
            max_pool_size=3,
        )
        pool_type.return_value.request.assert_not_awaited()
        await client.request({"insert": "items"})
        assert pool_type.return_value.request.await_args.args[0][
            "writeConcern"
        ] == {"w": 2}
        await client.close()


async def test_from_uri_delegates_discovery_and_preserves_write_concern() -> (
    None
):
    uri = "mongodb://seed/?w=2&journal=true&wTimeoutMS=50"
    parsed = await parse_uri(uri)
    pool = MagicMock(spec=ConnectionPool)
    with (
        patch("kover.client.parse_uri", new=AsyncMock(return_value=parsed)),
        patch.object(
            ConnectionPool,
            "from_parsed_uri",
            return_value=pool,
        ) as factory,
    ):
        client = await Kover.from_uri(uri)
        factory.assert_awaited_once_with(parsed, loop=None)
        await client.request({"insert": "items"})
        assert pool.request.await_args.args[0]["writeConcern"] == {
            "w": 2,
            "j": True,
            "wtimeout": 50,
        }


async def test_client_command_wrappers_and_result_mapping() -> None:
    client, pool = client_mock()
    pool.request.return_value = {
        "databases": [{"name": "one"}, {"name": "two"}],
    }
    assert await client.list_database_names() == ["one", "two"]
    await client.drop_database("test")
    assert pool.request.await_args.kwargs["db_name"] == "test"
    await client.drop_connections(["host:27017"], comment="test")
    assert pool.request.await_args.args[0] == {
        "dropConnections": 1,
        "hostAndPort": ["host:27017"],
        "comment": "test",
    }
    await client.logout()
    assert pool.request.await_args.args[0] == {"logout": 1}
    pool.request.return_value = {"argv": ["mongod", "--port", "27017"]}
    assert await client.get_commandline() == ["mongod", "--port", "27017"]
    pool.request.return_value = {"log": ['{"message": "test"}']}
    assert await client.get_log() == [{"message": "test"}]


async def test_administrative_commands_never_touch_a_real_server() -> None:
    client, pool = client_mock()
    await client.replica_set_initiate()
    assert pool.request.await_args.args[0] == {"replSetInitiate": {}}
    config = ReplicaSetConfig.default()
    await client.replica_set_initiate(config)
    assert pool.request.await_args.args[0] == {
        "replSetInitiate": config.to_dict(),
    }
    await client.replica_set_reconfig(config, force=True, max_time_ms=100)
    assert pool.request.await_args.args[0] == {
        "replSetReconfig": config.to_dict(),
        "force": True,
        "maxTimeMS": 100,
    }
    pool.request.return_value = {"ok": 1, "members": []}
    assert await client.get_replica_set_status() == {"ok": 1, "members": []}
    await client.rename_collection(
        "test.one", new_name="test.two", drop_target=True,
    )
    sent = pool.request.await_args.args[0]
    assert sent["renameCollection"] == "test.one"
    assert sent["to"] == "test.two"
    assert sent["dropTarget"] is True
    await client.set_user_write_block_mode(param=True)
    assert pool.request.await_args.args[0] == {
        "setUserWriteBlockMode": 1,
        "global": True,
    }
    await client.fsync(timeout=100, lock=False, comment="test")
    assert pool.request.await_args.args[0] == {
        "fsync": 1,
        "fsyncLockAcquisitionTimeoutMillis": 100,
        "lock": False,
        "comment": "test",
    }
    await client.fsync_unlock("test")
    assert pool.request.await_args.args[0] == {
        "fsyncUnlock": 1,
        "comment": "test",
    }
    await client.set_parameter("testParameter", 42)
    assert pool.request.await_args.args[0] == {
        "setParameter": 1,
        "testParameter": 42,
    }
    pool.request.return_value = {"testParameter": 42}
    assert await client.get_parameter("testParameter") == 42
    pool.request.return_value = {
        "defaultReadConcern": {"level": "majority"},
        "defaultWriteConcern": {"w": 2},
    }
    read, write = await client.get_default_rw_concern(in_memory=True)
    assert read.level == "majority"
    assert write.w == 2


async def test_build_info_maps_openssl_and_server_fields() -> None:
    client, pool = client_mock()
    pool.request.return_value = {
        "version": "8.2.1",
        "gitVersion": "test",
        "allocator": "tcmalloc",
        "javascriptEngine": "mozjs",
        "versionArray": [8, 2, 1, 0],
        "openssl": {"running": "OpenSSL test"},
        "debug": False,
        "maxBsonObjectSize": 16777216,
        "storageEngines": ["wiredTiger"],
    }
    info = await client.build_info()
    assert info.version == "8.2.1"
    assert info.openssl == "OpenSSL test"
