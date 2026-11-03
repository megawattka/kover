from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from kover import Kover
from kover.enums import TxnState
from kover.network import ConnectionPool
from kover.network.codec import CommandCodec
from kover.session import Session


def test_public_operations_use_session_only() -> None:
    for owner, name in (
        (Kover, "request"),
    ):
        assert "transaction" not in inspect.signature(
            getattr(owner, name),
        ).parameters


def test_codec_does_not_mutate_command() -> None:
    command = {"ping": 1}
    message = CommandCodec().encode(command, "admin", request_id=4)
    assert command == {"ping": 1}
    assert len(message) > 16


def test_session_contains_no_connection_and_adds_metadata() -> None:
    session = Session({"id": "logical"}, SimpleNamespace())  # type: ignore[arg-type]
    session.start_transaction()
    command = {"insert": "items"}
    session.apply_to(command)
    assert command["lsid"] == {"id": "logical"}
    assert command["txnNumber"] == 0
    assert command["startTransaction"] is True
    assert session.state is TxnState.IN_PROGRESS
    assert not hasattr(session, "connection")


@pytest.mark.asyncio
async def test_lease_returns_connection_and_rejects_after_release() -> None:
    pool = ConnectionPool(max_pool_size=1)
    lease = await pool.acquire()
    _ = lease.connection
    await lease.release(discard=True)
    with pytest.raises(RuntimeError, match="released"):
        _ = lease.connection
    assert pool.stats().checked_out == 0
    await pool.close()
