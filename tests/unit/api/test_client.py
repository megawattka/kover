from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from kover.client import Kover
from kover.execution.context import CommandReply
from kover.execution.executor import CommandExecutor
from kover.execution.protocols import ICommandExecutor
from kover.models.address import Address
from kover.models.concerns import WriteConcern
from kover.models.read_preference import ReadPreference
from kover.models.tx_state import TxnState
from kover.session import Session


def test_constructor_only_accepts_executor_and_write_concern() -> None:
    assert list(inspect.signature(Kover).parameters) == [
        "executor",
        "write_concern",
    ]
    assert not {"from_uri", "make_client", "_create_executor", "pool"} & (
        Kover.__dict__.keys()
    )


async def test_command_delegates_without_preparing_or_copying_document() -> (
    None
):
    executor = AsyncMock(spec=ICommandExecutor)
    reply = {"ok": 1}
    executor.execute.return_value = reply
    concern = WriteConcern(w=2)
    client = Kover(executor, write_concern=concern)
    session = Session({"id": "session"}, client)
    preference = ReadPreference(mode="nearest")
    address = Address(host="db")
    command = {"insert": "items"}

    assert (
        await client.command(
            command,
            db_name="shop",
            session=session,
            deadline=42,
            read_preference=preference,
            server_address=address,
        )
        is reply
    )

    executor.execute.assert_awaited_once_with(
        command,
        database="shop",
        session=session,
        deadline=42,
        read_preference=preference,
        server_address=address,
        write_concern=concern,
    )
    assert executor.execute.await_args.args[0] is command
    assert command == {"insert": "items"}


async def test_command_uses_operation_override_and_updated_default() -> None:
    executor = AsyncMock(spec=ICommandExecutor)
    client = Kover(executor)
    override = WriteConcern(w=1)
    await client.command({"insert": "items"}, write_concern=override)
    assert executor.execute.await_args.kwargs["write_concern"] is override

    assert client.set_write_concern(w=2, j=True, wtimeout=100) is client
    await client.command({"insert": "items"})
    assert executor.execute.await_args.kwargs["write_concern"] == WriteConcern(
        w=2,
        j=True,
        wtimeout=100,
    )


async def test_foreign_session_is_rejected_before_execution() -> None:
    executor = AsyncMock(spec=ICommandExecutor)
    client = Kover(executor)
    foreign = Kover(AsyncMock(spec=ICommandExecutor))
    session = Session({}, foreign)
    with pytest.raises(ValueError, match="different client"):
        await client.command({"ping": 1}, session=session)
    executor.execute.assert_not_awaited()


async def test_context_manager_closes_executor_and_propagates_errors() -> None:
    executor = AsyncMock(spec=ICommandExecutor)
    client = Kover(executor)
    error = RuntimeError("operation failed")

    async def fail_inside_context() -> None:
        async with client as entered:
            assert entered is client
            raise error

    with pytest.raises(RuntimeError, match="operation failed") as caught:
        await fail_inside_context()
    assert caught.value is error
    executor.close.assert_awaited_once_with()


async def test_administrative_and_session_helpers_use_executor() -> None:
    executor = AsyncMock(spec=ICommandExecutor)
    client = Kover(executor)
    executor.execute.return_value = {"id": {"id": "session"}}
    session = await client.start_session()
    assert session.client is client
    assert session.document == {"id": "session"}
    await client.refresh_sessions([session])
    assert executor.execute.await_args.args[0] == {
        "refreshSessions": [session.document],
    }
    await client.drop_database("shop")
    assert executor.execute.await_args.args[0] == {"dropDatabase": 1.0}
    assert executor.execute.await_args.kwargs["database"] == "shop"


@pytest.mark.parametrize(
    ("command", "explicit", "transaction", "expected"),
    [
        ({"insert": "items"}, None, False, {"w": 2}),
        ({"insert": "items"}, WriteConcern(w=1), False, {"w": 1}),
        ({"find": "items"}, None, False, None),
        ({"insert": "items"}, None, True, None),
        ({"insert": "items", "writeConcern": {"w": 3}}, None, False, {"w": 3}),
    ],
)
async def test_client_executor_pipeline_prepares_write_concern(
    command: dict[str, object],
    explicit: WriteConcern | None,
    *,
    transaction: bool,
    expected: dict[str, object] | None,
) -> None:
    address = Address(host="db")
    selector = MagicMock()
    selector.select = AsyncMock(return_value=address)
    pools = MagicMock()
    pool = pools.for_server.return_value
    pool.execute = AsyncMock(return_value={"ok": 1})
    pools.close = AsyncMock()
    executor = CommandExecutor(selector=selector, pools=pools)
    client = Kover(executor, write_concern=WriteConcern(w=2))
    session = Session({"id": "session"}, client) if transaction else None
    if session is not None:
        session.start_transaction()
    original = command.copy()

    reply = await client.command(
        command,
        write_concern=explicit,
        session=session,
    )

    assert isinstance(reply, CommandReply)
    assert reply.server_address == address
    assert reply == {"ok": 1}
    assert pool.execute.await_args is not None
    prepared = pool.execute.await_args.args[0]
    assert prepared.get("writeConcern") == expected
    assert command == original
    if session is not None:
        assert prepared["startTransaction"] is True
        assert prepared["lsid"] == session.document
        assert session.state is TxnState.IN_PROGRESS
        assert session.pinned_server_address == address
    await client.close()
    pools.close.assert_awaited_once_with()


def test_private_attributes_do_not_resolve_as_databases() -> None:
    client = Kover(AsyncMock(spec=ICommandExecutor))
    with pytest.raises(AttributeError, match="_missing"):
        getattr(client, "_" + "missing")
