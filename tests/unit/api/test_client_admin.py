from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from kover.client import Kover
from kover.models.concerns import ReadConcern, WriteConcern
from kover.models.replica_set import ReplicaSetConfig


def make_client() -> tuple[Kover, AsyncMock]:
    executor = AsyncMock()
    executor.execute.return_value = {"ok": 1}
    return Kover(executor), executor


async def test_build_info_helper() -> None:
    client, executor = make_client()
    executor.execute.return_value = {
        "version": "8.0.1",
        "gitVersion": "revision",
        "allocator": "system",
        "modules": ["enterprise"],
        "javascriptEngine": "mozjs",
        "versionArray": [8, 0, 1, 0],
        "debug": False,
        "bits": 64,
        "maxBsonObjectSize": 16777216,
        "storageEngines": ["wiredTiger"],
        "ok": 1,
    }
    info = await client.build_info()
    assert info.version == "8.0.1"
    assert info.git_version == "revision"
    await client.close()


async def test_default_rw_concern_returns_models_and_parameter_helpers() -> (
    None
):
    client, executor = make_client()
    executor.execute.return_value = {
        "defaultReadConcern": {"level": "majority"},
        "defaultWriteConcern": {"w": 3},
    }
    concerns = await client.get_default_rw_concern(in_memory=True)
    assert concerns == (ReadConcern(level="majority"), WriteConcern(w=3))
    assert executor.execute.await_args.args[0] == {
        "getDefaultRWConcern": 1.0,
        "inMemory": True,
    }

    executor.execute.return_value = {"featureFlag": True}
    assert await client.get_parameter("featureFlag") is True
    assert executor.execute.await_args.args[0] == {
        "getParameter": 1.0,
        "featureFlag": 1.0,
    }
    await client.set_parameter("featureFlag", value=False)
    assert executor.execute.await_args.args[0] == {
        "setParameter": 1.0,
        "featureFlag": False,
    }
    await client.close()


async def test_database_management_helpers_forward_arguments() -> None:
    client, executor = make_client()
    executor.execute.return_value = {
        "databases": [{"name": "shop"}],
        "totalSize": 12,
        "ok": 1,
    }
    assert await client.list_database_names() == ["shop"]
    assert executor.execute.await_args.args[0] == {
        "listDatabases": 1.0,
        "nameOnly": True,
    }

    executor.execute.return_value = {"n": 2, "ok": 1}
    await client.drop_database("shop")
    assert executor.execute.await_args.kwargs["database"] == "shop"
    assert executor.execute.await_args.args[0] == {"dropDatabase": 1.0}
    await client.close()


async def test_replica_set_commands_forward_config_and_status() -> None:
    client, executor = make_client()
    config = ReplicaSetConfig.default()
    executor.execute.return_value = {"ok": 1}
    result = await client.replica_set_initiate(config)
    assert result is None
    assert executor.execute.await_args.args[0]["replSetInitiate"] == (
        config.model_dump()
    )
    await client.replica_set_reconfig(
        config,
        force=True,
        max_time_ms=100,
    )
    assert executor.execute.await_args.args[0] == {
        "replSetReconfig": config.model_dump(),
        "force": True,
        "maxTimeMS": 100,
    }
    executor.execute.return_value = {"members": [], "ok": 1}
    assert await client.get_replica_set_status() == {"members": [], "ok": 1}
    assert executor.execute.await_args.args[0] == {"replSetGetStatus": 1.0}
    await client.close()


async def test_sessions_ownership_is_validated() -> None:
    client, executor = make_client()
    executor.execute.return_value = {"id": {"id": "logical"}}
    session = await client.start_session()
    assert session.client is client
    assert session.document == {"id": "logical"}
    await client.refresh_sessions([session])
    assert executor.execute.await_args.args[0] == {
        "refreshSessions": [session.document],
    }
    await client.end_sessions([session])
    assert executor.execute.await_args.args[0] == {
        "endSessions": [session.document],
    }
    foreign_executor = AsyncMock()
    foreign_executor.execute.return_value = {"id": {"id": "foreign"}}
    foreign_client = Kover(foreign_executor)
    with pytest.raises(ValueError, match="foreign"):
        await client.refresh_sessions([await foreign_client.start_session()])
    executor.execute.reset_mock()
    with pytest.raises(ValueError, match="foreign"):
        await client.end_sessions([await foreign_client.start_session()])
    executor.execute.assert_not_awaited()
    await client.close()
    await foreign_client.close()
