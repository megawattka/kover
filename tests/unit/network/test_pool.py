from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from kover.exceptions import PoolClosedError, PoolTimeoutError
from kover.models.address import Address
from kover.network import ConnectionPool

if TYPE_CHECKING:
    from kover.network import Connection, ConnectionLease


def connection(*, usable: bool = True) -> MagicMock:
    instance = MagicMock()
    instance.usable = usable
    instance.close = AsyncMock()
    return instance


def test_pool_rejects_nonpositive_capacity() -> None:
    with pytest.raises(ValueError, match="max_pool_size"):
        ConnectionPool(Address(host="db"), AsyncMock(), max_pool_size=0)


async def test_checkout_reuses_connection_and_obeys_size_limit() -> None:
    first = connection()
    factory = AsyncMock(return_value=first)
    pool = ConnectionPool(Address(host="db"), factory, max_pool_size=1)

    lease = await pool.acquire()
    entered = asyncio.Event()

    async def acquire_after_signal() -> ConnectionLease:
        entered.set()
        return await pool.acquire()

    waiter = asyncio.create_task(acquire_after_signal())
    await asyncio.wait_for(entered.wait(), timeout=1)
    assert not waiter.done()

    await lease.release()
    second_lease: ConnectionLease = await asyncio.wait_for(waiter, timeout=1)
    assert second_lease.connection is first
    factory.assert_awaited_once()
    await second_lease.release()
    await pool.close()
    first.close.assert_awaited_once()


async def test_checkout_deadline_expires_while_pool_is_full() -> None:
    first = connection()
    pool = ConnectionPool(
        Address(host="db"),
        AsyncMock(return_value=first),
        max_pool_size=1,
    )
    lease = await pool.acquire()
    deadline = asyncio.get_running_loop().time() + 0.005
    with pytest.raises(PoolTimeoutError, match="checkout deadline"):
        await pool.acquire(deadline=deadline)
    await lease.release()
    await pool.close()


async def test_creation_deadline_and_close_during_creation() -> None:
    started = asyncio.Event()

    async def blocked_factory() -> Connection:  # pyright: ignore[reportReturnType]
        started.set()
        await asyncio.Event().wait()

    pool = ConnectionPool(
        Address(host="db"),
        blocked_factory,
        max_pool_size=1,
    )
    deadline = asyncio.get_running_loop().time() + 0.03
    with pytest.raises(PoolTimeoutError, match="creation exceeded"):
        await pool.acquire(deadline=deadline)

    pending = asyncio.create_task(pool.acquire())
    await asyncio.wait_for(started.wait(), timeout=1)
    await pool.close()
    with pytest.raises(PoolClosedError):
        await asyncio.wait_for(pending, timeout=1)


async def test_cancelled_creation_propagates_and_frees_slot() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    replacement = connection()

    async def factory() -> MagicMock:
        entered.set()
        await release.wait()
        return replacement

    create = AsyncMock(side_effect=factory)
    pool = ConnectionPool(Address(host="db"), create, max_pool_size=1)
    task = asyncio.create_task(pool.acquire())
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    create.side_effect = None
    create.return_value = replacement
    lease = await asyncio.wait_for(pool.acquire(), timeout=1)
    assert lease.connection is replacement
    await lease.release()
    await pool.close()


@pytest.mark.parametrize("close_fails", [False, True])
async def test_cancelled_checkout_after_creation_frees_slot(
    *,
    close_fails: bool,
) -> None:
    entered = asyncio.Event()
    finish_creation = asyncio.Event()
    created = asyncio.Event()
    abandoned = connection()
    replacement = connection()
    if close_fails:
        abandoned.close.side_effect = OSError("close failed")

    async def factory() -> MagicMock:
        entered.set()
        await finish_creation.wait()
        created.set()
        return abandoned

    create = AsyncMock(side_effect=factory)
    pool = ConnectionPool(Address(host="db"), create, max_pool_size=1)
    task = asyncio.create_task(pool.acquire())
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        # Prevent registration after the factory returns the connection.
        async with pool._condition:  # pyright: ignore[reportPrivateUsage] # ruff: ignore[private-member-access]
            finish_creation.set()
            await asyncio.wait_for(created.wait(), timeout=1)
            assert not task.done()
            task.cancel()

        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(task, timeout=1)
        abandoned.close.assert_awaited_once()
        if close_fails:
            assert any(
                "close failed" in note for note in caught.value.__notes__
            )

        create.side_effect = None
        create.return_value = replacement
        lease = await asyncio.wait_for(pool.acquire(), timeout=1)
        assert lease.connection is replacement
        await lease.release()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await pool.close()


async def test_close_after_creation_closes_unregistered_connection() -> None:
    pool_closed = asyncio.Event()
    abandoned = connection()

    async def factory() -> MagicMock:
        await pool.close()
        pool_closed.set()
        return abandoned

    pool = ConnectionPool(Address(host="db"), factory, max_pool_size=1)
    with pytest.raises(PoolClosedError, match="during connection creation"):
        await asyncio.wait_for(pool.acquire(), timeout=1)
    assert pool_closed.is_set()
    abandoned.close.assert_awaited_once()
    await pool.close()


async def test_unusable_and_unknown_connections_are_handled() -> None:
    dead = connection(usable=False)
    pool = ConnectionPool(Address(host="db"), AsyncMock(return_value=dead))
    lease = await pool.acquire()
    await lease.release()
    dead.close.assert_awaited_once()
    with pytest.raises(RuntimeError, match="not checked out"):
        await pool.release(dead)
    await pool.close()


async def test_execute_discards_unusable_connection() -> None:
    instance = connection(usable=False)
    instance.command = AsyncMock(side_effect=OSError("socket broken"))
    pool = ConnectionPool(Address(host="db"), AsyncMock(return_value=instance))
    with pytest.raises(OSError, match="socket broken"):
        await pool.execute({"ping": 1}, database="admin", deadline=None)
    instance.close.assert_awaited_once()
    await pool.close()


async def test_async_context_manager_closes_and_rejects_reentry() -> None:
    pool = ConnectionPool(Address(host="db"), AsyncMock())
    async with pool as entered:
        assert entered is pool
    assert pool.closed
    with pytest.raises(PoolClosedError, match="pool is closed"):
        async with pool:
            pytest.fail("closed pool unexpectedly entered")


async def test_factory_failure_releases_reserved_capacity() -> None:
    replacement = connection()
    factory = AsyncMock(
        side_effect=[OSError("connection failed"), replacement],
    )
    pool = ConnectionPool(Address(host="db"), factory, max_pool_size=1)
    with pytest.raises(OSError, match="connection failed"):
        await pool.acquire()
    lease = await pool.acquire()
    assert lease.connection is replacement
    await lease.release()
    await pool.close()


async def test_discard_closes_connection_and_close_rejects_new_work() -> None:
    first = connection()
    pool = ConnectionPool(Address(host="db"), AsyncMock(return_value=first))
    lease = await pool.acquire()
    await lease.release(discard=True)
    first.close.assert_awaited_once()
    await pool.close()
    with pytest.raises(PoolClosedError):
        await pool.acquire()


async def test_close_defers_checked_out_connection_close_until_release() -> (
    None
):
    first = connection()
    pool = ConnectionPool(Address(host="db"), AsyncMock(return_value=first))
    lease = await pool.acquire()
    await pool.close()
    first.close.assert_not_awaited()
    await lease.release()
    first.close.assert_awaited_once()
    assert pool.closed
