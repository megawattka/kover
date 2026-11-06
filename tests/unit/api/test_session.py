from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from bson import Int64
import pytest

from kover.client import Kover
from kover.exceptions import OperationFailure
from kover.execution.executor import CommandExecutor
from kover.models.address import Address
from kover.models.tx_state import TxnState
from kover.session import Session


def make_session() -> tuple[Session, AsyncMock]:
    executor = AsyncMock()
    executor.execute.return_value = {"ok": 1}
    client = Kover(executor)
    return Session({"id": "session"}, client), executor


def test_transaction_state_and_metadata_lifecycle() -> None:
    session, _ = make_session()
    metadata: dict[str, object] = {}
    session.apply_to(metadata)
    assert metadata == {"lsid": session.document}
    assert session.state is TxnState.NONE
    assert not session.in_transaction

    options = {"readConcern": {"level": "snapshot"}}
    session.start_transaction(options)
    assert session.state is TxnState.STARTING
    assert session.tx_id == Int64(0)
    with pytest.raises(ValueError, match="active transaction"):
        session.start_transaction()

    first: dict[str, object] = {}
    starts_transaction = session.apply_to(first)
    assert first == {
        "lsid": session.document,
        "startTransaction": True,
        "txnNumber": Int64(0),
        "autocommit": False,
    }
    assert starts_transaction
    assert session.state is TxnState.STARTING
    session.mark_transaction_started()
    assert session.state is TxnState.IN_PROGRESS
    second: dict[str, object] = {}
    session.apply_to(second)
    assert second == {
        "lsid": session.document,
        "txnNumber": Int64(0),
        "autocommit": False,
    }
    assert session.state is TxnState.IN_PROGRESS
    assert options == {"readConcern": {"level": "snapshot"}}

    session.pin_server(Address(host="db"))
    with pytest.raises(ValueError, match="another server"):
        session.pin_server(Address(host="other"))
    session.unpin_server()
    assert session.pinned_server_address is None


async def test_failed_first_tx_command_retries_start_metadata() -> None:
    address = Address(host="db")
    selector = MagicMock()
    selector.select = AsyncMock(return_value=address)
    selector.invalidate = MagicMock()
    selector.description.return_value.server_type = "Standalone"
    pools = MagicMock()
    pool = pools.for_server.return_value
    pool.execute = AsyncMock()
    pools.close = AsyncMock()
    error = OSError("network unavailable")
    pool.execute.side_effect = [error, {"ok": 1}]
    executor = CommandExecutor(selector=selector, pools=pools)
    client = Kover(executor)
    session = Session({"id": "session"}, client)
    session.start_transaction()

    with pytest.raises(OSError, match="network unavailable") as caught:
        await session.client.command(
            {"insert": "items", "documents": [{"value": 1}]},
            db_name="shop",
            session=session,
        )

    assert caught.value is error
    assert session.state is TxnState.STARTING
    await session.client.command(
        {"insert": "items", "documents": [{"value": 1}]},
        db_name="shop",
        session=session,
    )
    assert pool.execute.await_args_list[0].args[0]["startTransaction"] is True
    assert pool.execute.await_args_list[1].args[0]["startTransaction"] is True
    assert session.state is TxnState.IN_PROGRESS
    await client.close()


@pytest.mark.parametrize(
    "failure",
    [
        OSError("socket closed"),
        OperationFailure(10107, "not primary"),
        OperationFailure(2, "bad value"),
    ],
)
async def test_executor_invalidates_only_on_network_or_topology_failure(
    failure: OperationFailure,
) -> None:
    address = Address(host="db")
    selector = MagicMock()
    selector.select = AsyncMock(return_value=address)
    selector.description.return_value.server_type = "Standalone"
    selector.invalidate = MagicMock()
    pools = MagicMock()
    pool = pools.for_server.return_value
    pool.execute = AsyncMock(side_effect=failure)
    pools.close = AsyncMock()
    client = Kover(CommandExecutor(selector=selector, pools=pools))

    with pytest.raises(type(failure)) as caught:
        await client.command({"ping": 1})

    assert caught.value is failure
    if isinstance(failure, OSError) or failure.code == 10107:
        selector.invalidate.assert_called_once_with(address)
    else:
        selector.invalidate.assert_not_called()
    await client.close()


async def test_commit_success_advances_transaction_and_is_idempotent() -> None:
    session, executor = make_session()
    session.start_transaction()
    session.pin_server(Address(host="db"))
    await session.commit_transaction(deadline=12)
    assert session.state is TxnState.COMMITTED
    assert session.pinned_server_address is None
    await session.commit_transaction()
    assert executor.execute.await_count == 1
    assert executor.execute.await_args.kwargs["deadline"] == 12

    session.start_transaction()
    assert session.tx_id == Int64(1)
    await session.abort_transaction()
    assert session.state is TxnState.ABORTED
    await session.close()
    await session.client.close()


@pytest.mark.parametrize(
    ("unknown", "expected_state"),
    [
        (False, TxnState.ABORTED),
        (True, TxnState.COMMITTING),
    ],
)
async def test_commit_failure_changes_state_by_error_label(
    *,
    unknown: bool,
    expected_state: TxnState,
) -> None:
    session, executor = make_session()
    session.start_transaction()
    session.pin_server(Address(host="db"))
    error = OperationFailure(91, "commit failed")
    if unknown:
        error.error_labels = frozenset({"UnknownTransactionCommitResult"})
    executor.execute.side_effect = error

    with pytest.raises(OperationFailure) as caught:
        await session.commit_transaction()
    assert caught.value is error
    assert session.state is expected_state
    if unknown:
        assert session.pinned_server_address == Address(host="db")
    else:
        assert session.pinned_server_address is None
    await session.client.close()


async def test_abort_tolerates_missing_transaction_and_always_unpins() -> None:
    session, executor = make_session()
    with pytest.raises(ValueError, match="no active transaction"):
        await session.abort_transaction()
    session.start_transaction()
    session.pin_server(Address(host="db"))
    executor.execute.side_effect = OperationFailure(251, "not active")
    await session.abort_transaction(deadline=5)
    assert session.state is TxnState.ABORTED
    assert session.pinned_server_address is None
    assert executor.execute.await_args.kwargs["deadline"] == 5
    await session.abort_transaction()
    assert executor.execute.await_count == 1
    await session.client.close()


async def test_abort_propagates_other_errors_but_clears_transaction() -> None:
    session, executor = make_session()
    session.start_transaction()
    session.pin_server(Address(host="db"))
    error = OperationFailure(8, "abort failed")
    executor.execute.side_effect = error
    with pytest.raises(OperationFailure) as caught:
        await session.abort_transaction()
    assert caught.value is error
    assert session.state is TxnState.ABORTED
    assert session.pinned_server_address is None
    await session.client.close()


async def test_close_aborts_and_repr_uses_binary_session_id() -> None:
    session, executor = make_session()
    session.document = {"id": b"\x01\x02"}
    assert "0102" in repr(session)
    session.start_transaction()
    await session.close()
    assert session.state is TxnState.ABORTED
    assert executor.execute.await_args.args[0] == {"abortTransaction": 1.0}
    await session.close()
    assert executor.execute.await_count == 1
    await session.client.close()
