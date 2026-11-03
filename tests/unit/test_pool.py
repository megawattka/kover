from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from kover import Kover
from kover.enums import PoolState
from kover.exceptions import (
    NetworkError,
    OperationFailure,
    PoolClosedError,
    PoolPausedError,
    PoolTimeoutError,
)
from kover.models import HelloResult
from kover.models.network import Address
from kover.network.connection import Connection
from kover.network.discovery import DiscoveryOptions
from kover.network.pool import ConnectionPool
from kover.session import Session
from kover.uri_parser import parse_uri


def socket_mock(*, usable: bool = True) -> MagicMock:
    connection = MagicMock(spec=Connection)
    connection.usable = usable
    connection.command.return_value = {"ok": 1}
    connection.hello.return_value = MagicMock(spec=HelloResult)
    connection.hello.return_value.requires_auth = False
    return connection


@pytest.mark.parametrize("size", [0, -1])
def test_invalid_pool_size(size: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        ConnectionPool(max_pool_size=size)


async def test_lazy_creation_reuse_and_idempotent_release() -> None:
    connection = socket_mock()
    with patch.object(
        ConnectionPool,
        "_create_connection",
        return_value=connection,
    ) as factory:
        pool = ConnectionPool(max_pool_size=1)
        factory.assert_not_called()
        assert pool.stats().idle == pool.stats().checked_out == 0
        lease = await pool.acquire()
        assert lease.connection is connection
        assert pool.stats().checked_out == 1
        await lease.release()
        await lease.release(discard=True)
        assert pool.stats().idle == 1
        with pytest.raises(RuntimeError, match="released"):
            _ = lease.connection
        async with await pool.acquire() as reused:
            assert reused is connection
        factory.assert_called_once()
        await pool.close()
        await pool.close()
        connection.close.assert_awaited_once()


@pytest.mark.parametrize(
    "error",
    [RuntimeError("body"), asyncio.CancelledError()],
)
async def test_lease_exception_discards_connection(
    error: BaseException,
) -> None:
    connection = socket_mock()
    with patch.object(
        ConnectionPool,
        "_create_connection",
        return_value=connection,
    ):
        pool = ConnectionPool(max_pool_size=1)
        with pytest.raises(type(error)):
            async with await pool.acquire():
                raise error
        assert pool.stats().checked_out == pool.stats().idle == 0
        connection.close.assert_awaited_once()
        await pool.close()


async def test_bounded_checkout_waits_for_release() -> None:
    with patch.object(
        ConnectionPool,
        "_create_connection",
        side_effect=socket_mock,
    ):
        pool = ConnectionPool(max_pool_size=2)
        first, second = await pool.acquire(), await pool.acquire()
        waiter = asyncio.create_task(pool.acquire())
        try:
            await asyncio.sleep(0)
            assert not waiter.done()
            assert pool.stats().checked_out == 2
            connection = first.connection
            await first.release()
            third = await asyncio.wait_for(waiter, 1)
            assert third.connection is connection
            await third.release()
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
            await second.release()
            await pool.close()


async def test_checkout_deadline_and_cancel_leave_no_resource_loss() -> None:
    with patch.object(
        ConnectionPool,
        "_create_connection",
        side_effect=socket_mock,
    ):
        pool = ConnectionPool(max_pool_size=1)
        lease = await pool.acquire()
        with pytest.raises(PoolTimeoutError):
            await pool.acquire(
                deadline=asyncio.get_running_loop().time() + 0.01,
            )
        waiter = asyncio.create_task(pool.acquire())
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert pool.stats().checked_out == 1
        await lease.release()
        assert pool.stats().idle == 1
        await pool.close()


async def test_close_wakes_waiters_and_discards_late_returns() -> None:
    connection = socket_mock()
    with patch.object(
        ConnectionPool,
        "_create_connection",
        return_value=connection,
    ):
        pool = ConnectionPool(max_pool_size=1)
        lease = await pool.acquire()
        waiter = asyncio.create_task(pool.acquire())
        await asyncio.sleep(0)
        await pool.close()
        with pytest.raises(PoolClosedError):
            await asyncio.wait_for(waiter, 1)
        await lease.release()
        connection.close.assert_awaited_once()
        assert pool.stats().checked_out == pool.stats().idle == 0
        assert pool.state is PoolState.CLOSED
        with pytest.raises(PoolClosedError):
            pool.ready()


async def test_clear_pauses_discards_idle_and_ready_resumes() -> None:
    connection = socket_mock()
    with patch.object(
        ConnectionPool,
        "_create_connection",
        return_value=connection,
    ):
        pool = ConnectionPool(max_pool_size=1)
        lease = await pool.acquire()
        await lease.release()
        await pool.clear()
        await asyncio.sleep(0)
        connection.close.assert_awaited_once()
        assert pool.state is PoolState.PAUSED
        assert pool.stats().idle == 0
        with pytest.raises(PoolPausedError):
            await pool.acquire()
        pool.ready()
        assert pool.state is PoolState.READY
        await (await pool.acquire()).release(discard=True)
        await pool.close()


@pytest.mark.parametrize(
    "error",
    [
        NetworkError("broken"),
        ValueError("decode"),
        asyncio.CancelledError(),
    ],
)
async def test_request_failure_discards_connection(
    error: BaseException,
) -> None:
    connection = socket_mock()
    connection.command.side_effect = error
    with patch.object(
        ConnectionPool,
        "_create_connection",
        return_value=connection,
    ):
        pool = ConnectionPool(max_pool_size=1)
        with pytest.raises(type(error)):
            await pool.request({"ping": 1})
        connection.close.assert_awaited_once()
        assert pool.stats().checked_out == pool.stats().idle == 0
        await pool.close()


async def test_server_error_preserves_connection_and_reuses_it() -> None:
    connection = socket_mock()
    connection.command.side_effect = [
        OperationFailure(13, "denied"),
        {"ok": 1},
    ]
    with patch.object(
        ConnectionPool,
        "_create_connection",
        return_value=connection,
    ) as factory:
        pool = ConnectionPool(max_pool_size=1)
        with pytest.raises(OperationFailure):
            await pool.request({"ping": 1})
        connection.close.assert_not_awaited()
        assert await pool.request({"ping": 1}) == {"ok": 1}
        factory.assert_called_once()
        await pool.close()


@pytest.mark.parametrize("stage", ["connect", "hello", "authorize"])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_failed_initialization_closes_and_allows_replacement(
    stage: str,
    *,
    cancelled: bool,
) -> None:
    broken, replacement = socket_mock(usable=False), socket_mock()
    broken.hello.return_value.requires_auth = True
    error = asyncio.CancelledError() if cancelled else RuntimeError(stage)
    getattr(broken, stage).side_effect = error
    with patch.object(
        ConnectionPool,
        "_create_connection",
        side_effect=[broken, replacement],
    ):
        pool = ConnectionPool(max_pool_size=1)
        with pytest.raises(type(error)):
            await pool.request({"ping": 1})
        broken.close.assert_awaited_once()
        assert await pool.request({"ping": 1}) == {"ok": 1}
        await pool.close()


async def test_request_session_metadata_options_and_fire_and_forget() -> None:
    connection = socket_mock()
    with patch.object(
        ConnectionPool,
        "_create_connection",
        return_value=connection,
    ):
        pool = ConnectionPool(max_pool_size=1)
        session = Session({"id": "logical"}, Kover(pool=pool))
        session.start_transaction()
        document = {"insert": "items"}
        await pool.request(
            document,
            db_name="test",
            session=session,
            deadline=42,
        )
        sent = connection.command.await_args.args[0]
        assert sent["lsid"] == session.document
        assert sent["startTransaction"] is True
        assert sent["txnNumber"] == 0
        assert document == {"insert": "items"}
        assert connection.command.await_args.args[1] == "test"
        assert connection.command.await_args.kwargs == {"deadline": 42}
        assert pool.stats().checked_out == 0
        assert await pool.request({"shutdown": 1}, wait_response=False) == {}
        connection.fire_and_forget.assert_awaited_once_with(
            {"shutdown": 1},
            "admin",
            deadline=None,
        )
        await pool.close()


async def test_uri_discovery_preserves_options() -> None:
    parsed = await parse_uri(
        "mongodb://user:password@seed:27018/?tls=true&compressors=zlib"
        "&appName=test&maxPoolSize=3&replicaSet=rs"
        "&serverSelectionTimeoutMS=1200&connectTimeoutMS=300&authSource=auth",
    )
    with patch.object(
        ConnectionPool,
        "discover",
        return_value=MagicMock(spec=ConnectionPool),
    ) as discover:
        assert (
            await ConnectionPool.from_parsed_uri(parsed)
            is discover.return_value
        )
        discover.assert_awaited_once_with(
            [Address(host="seed", port=27018)],
            options=DiscoveryOptions(
                replica_set="rs",
                server_selection_timeout=1.2,
                connect_timeout=0.3,
            ),
            credentials=parsed.credentials,
            loop=None,
            compression=["zlib"],
            tls=True,
            application={"name": "test"},
            max_pool_size=3,
        )


async def test_load_balanced_uri_is_rejected_before_connect() -> None:
    parsed = await parse_uri("mongodb://seed/?loadBalanced=true")
    with patch.object(ConnectionPool, "_create_connection") as factory:
        with pytest.raises(ValueError, match="loadBalanced"):
            await ConnectionPool.from_parsed_uri(parsed)
        factory.assert_not_called()
