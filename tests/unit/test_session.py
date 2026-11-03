from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from bson import Int64
import pytest

from kover import Kover
from kover.enums import TxnState
from kover.exceptions import OperationFailure
from kover.models.network import Address
from kover.session import Session

if TYPE_CHECKING:
    from kover.typings import DictT


def new_session() -> tuple[Session, AsyncMock]:
    client = MagicMock(spec=Kover)
    client.request = AsyncMock(return_value={"ok": 1})
    return Session({"id": "logical"}, client), client.request


async def test_local_start_increments_numbers_and_metadata_only_once() -> None:
    session, request = new_session()
    assert session.state is TxnState.NONE
    document: DictT = {}
    session.apply_to(document)
    assert document == {"lsid": session.document}
    for number in range(3):
        session.start_transaction()
        assert session.state is TxnState.STARTING
        assert session.tx_id == number
        assert isinstance(session.tx_id, Int64)
        with pytest.raises(ValueError, match="active"):
            session.start_transaction()
        assert session.tx_id == number
        first: DictT = {}
        second: DictT = {}
        session.apply_to(first)
        session.apply_to(second)
        assert first == {
            "lsid": session.document,
            "startTransaction": True,
            "txnNumber": number,
            "autocommit": False,
        }
        assert second == {
            "lsid": session.document,
            "txnNumber": number,
            "autocommit": False,
        }
        assert session.state is TxnState.IN_PROGRESS
        assert request.await_count == number
        await session.abort_transaction()
    assert request.await_count == 3


def test_server_pin_is_not_a_connection_pin() -> None:
    session, _ = new_session()
    address = Address(host="one")
    session.pin_server(address)
    session.pin_server(address)
    assert session.pinned_server_address == address
    with pytest.raises(ValueError, match="another server"):
        session.pin_server(Address(host="two"))
    session.unpin_server()
    assert session.pinned_server_address is None
    assert not hasattr(session, "connection")


@pytest.mark.parametrize("method", ["commit_transaction", "abort_transaction"])
async def test_completion_without_transaction_rejected(method: str) -> None:
    session, request = new_session()
    with pytest.raises(ValueError, match="no active"):
        await getattr(session, method)()
    request.assert_not_awaited()


@pytest.mark.parametrize(
    ("method", "command", "state"),
    [
        ("commit_transaction", "commitTransaction", TxnState.COMMITTED),
        ("abort_transaction", "abortTransaction", TxnState.ABORTED),
    ],
)
async def test_completion_is_idempotent_and_session_can_be_reused(
    method: str,
    command: str,
    state: TxnState,
) -> None:
    session, request = new_session()
    for number in range(3):
        session.start_transaction()
        session.pin_server(Address(host="one"))
        await getattr(session, method)(deadline=42)
        await getattr(session, method)()
        assert session.state is state
        assert not session.in_transaction
        assert session.tx_id == number
        assert session.pinned_server_address is None
        request.assert_awaited_with(
            {command: 1.0}, session=session, deadline=42,
        )
    assert request.await_count == 3


async def test_unknown_commit_keeps_retryable_state_and_pin() -> None:
    session, request = new_session()
    error = OperationFailure(64, "unknown")
    error.error_labels = frozenset({"UnknownTransactionCommitResult"})
    request.side_effect = [error, {"ok": 1}]
    session.start_transaction()
    session.pin_server(Address(host="one"))
    transaction_number = session.tx_id
    with pytest.raises(OperationFailure) as caught:
        await session.commit_transaction()
    assert caught.value is error
    assert session.state is TxnState.COMMITTING
    assert session.pinned_server_address is not None
    with pytest.raises(ValueError, match="active transaction"):
        session.start_transaction()
    document: DictT = {}
    session.apply_to(document)
    assert "startTransaction" not in document
    assert document["autocommit"] is False
    await session.commit_transaction()
    assert session.state is TxnState.COMMITTED
    assert session.tx_id == transaction_number


async def test_failed_commit_aborts_locally_and_unpins() -> None:
    session, request = new_session()
    request.side_effect = OperationFailure(251, "aborted")
    session.start_transaction()
    session.pin_server(Address(host="one"))
    with pytest.raises(OperationFailure):
        await session.commit_transaction()
    assert session.state is TxnState.ABORTED
    assert session.pinned_server_address is None


@pytest.mark.parametrize("code", [251, 13])
async def test_abort_already_aborted_or_other_server_failure(
    code: int,
) -> None:
    session, request = new_session()
    request.side_effect = OperationFailure(code, "abort failed")
    session.start_transaction()
    session.pin_server(Address(host="one"))
    if code == 251:
        await session.abort_transaction()
    else:
        with pytest.raises(OperationFailure):
            await session.abort_transaction()
    assert session.state is TxnState.ABORTED
    assert session.pinned_server_address is None
    await session.close()
    request.assert_awaited_once()


async def test_close_active_session_aborts_once() -> None:
    session, request = new_session()
    session.start_transaction()
    await session.close()
    await session.close()
    assert session.state is TxnState.ABORTED
    request.assert_awaited_once_with(
        {"abortTransaction": 1.0},
        session=session,
        deadline=None,
    )
