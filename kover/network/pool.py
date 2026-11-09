"""Bounded pool of initialized connections for one MongoDB server."""

from __future__ import annotations

import asyncio
from collections import deque
from typing import TYPE_CHECKING, Any, Self

from ..exceptions import PoolClosedError, PoolTimeoutError
from ..execution.protocols import IServerPool
from .lease import ConnectionLease

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from types import TracebackType

    from ..models.address import Address
    from .connection import Connection

    ConnectionFactory = Callable[[], Awaitable[Connection]]


class ConnectionPool(IServerPool):
    """Manage reusable connections for exactly one server address.

    ``connection_factory`` must return an open, handshaken connection ready
    for commands. The pool limits concurrent connections and guarantees that
    each checked-out connection has one exclusive owner.
    """

    def __init__(
        self,
        address: Address,
        connection_factory: ConnectionFactory,
        *,
        max_pool_size: int = 100,
        connection_timeout: float | None = 10.0,
    ) -> None:
        if max_pool_size < 1:
            raise ValueError("max_pool_size must be positive")

        self.address = address
        self._connection_factory = connection_factory
        self._max_pool_size = max_pool_size
        self._connection_timeout = connection_timeout
        self._idle: deque[Connection] = deque()
        self._condition = asyncio.Condition()
        self._total = 0
        self._checked_out: set[Connection] = set()
        self._closed = False

    @property
    def closed(self) -> bool:
        """Whether the pool has stopped accepting checkouts."""
        return self._closed

    @property
    def max_pool_size(self) -> int:
        """Maximum number of connections owned by this pool."""
        return self._max_pool_size

    async def acquire(
        self,
        *,
        deadline: float | None = None,
    ) -> ConnectionLease:
        """Acquire an exclusive connection lease.

        Cancellation propagates after releasing any reserved capacity and
        closing a newly created connection that has not been registered.

        Args:
            deadline: Absolute deadline measured by the event-loop clock.

        Returns:
            A lease returning the connection to this pool when released.

        Raises:
            PoolClosedError: if the pool closes before checkout completes.
        """
        connection = await self._take_idle_or_reserve(deadline)
        if connection is not None:
            return ConnectionLease(self, connection)

        try:
            connection = await self._create_connection(deadline)
            async with self._condition:
                if self._closed:
                    raise PoolClosedError(  # ruff: ignore[raise-within-try]
                        "pool closed during connection creation",
                    )
                self._checked_out.add(connection)
        except (Exception, asyncio.CancelledError) as error:
            # The reservation belongs to this checkout until registration,
            # including while it waits for the condition after creation.
            async with self._condition:
                self._total -= 1
                self._condition.notify_all()
            if connection is not None:
                try:
                    await connection.close()
                except (Exception, asyncio.CancelledError) as cleanup_error:  # ruff: ignore[blind-except]
                    error.add_note(
                        f"Connection cleanup also failed: {cleanup_error!r}",
                    )
            raise

        return ConnectionLease(self, connection)

    async def _take_idle_or_reserve(
        self,
        deadline: float | None,
    ) -> Connection | None:
        """Return an idle connection or reserve capacity for a new one.

        A ``None`` result means this caller owns a reserved capacity slot.

        Raises:
            PoolTimeoutError: if the pool is closed while waiting for capacity.
            PoolClosedError: if the pool is closed.
        """
        while True:
            async with self._condition:
                if self._closed:
                    if self._total:
                        raise PoolTimeoutError(
                            "pool closed while connection creation is pending",
                        )
                    raise PoolClosedError("connection pool is closed")

                connection = await self._take_usable_idle()
                if connection is not None:
                    self._checked_out.add(connection)
                    return connection

                if self._total < self._max_pool_size:
                    self._total += 1
                    return None

                await self._wait_for_capacity(deadline)

    async def _take_usable_idle(self) -> Connection | None:
        """Return the first live idle connection and discard stale entries."""
        while self._idle:
            connection = self._idle.popleft()
            if connection.usable:
                return connection

            self._total -= 1
            await connection.close()

        return None

    async def _wait_for_capacity(self, deadline: float | None) -> None:
        """Wait for a release or raise when the absolute deadline expires.

        Raises:
            PoolTimeoutError: if timeout occur.
        """
        try:
            async with asyncio.timeout_at(deadline):
                await self._condition.wait()
        except TimeoutError as e:
            raise PoolTimeoutError(
                "connection checkout deadline expired",
            ) from e

    async def _create_connection(self, deadline: float | None) -> Connection:
        """Create a handshaken connection, respecting the checkout deadline.

        Returns:
            A newly initialized connection.

        Raises:
            PoolTimeoutError: if timeout occur.
        """
        try:
            loop = asyncio.get_running_loop()
            limits = [
                value
                for value in (
                    deadline,
                    (
                        loop.time() + self._connection_timeout
                        if self._connection_timeout is not None
                        else None
                    ),
                )
                if value is not None
            ]
            timeout_deadline = min(limits) if limits else None
            async with asyncio.timeout_at(timeout_deadline):
                return await self._connection_factory()
        except TimeoutError as e:
            raise PoolTimeoutError(
                "connection creation exceeded checkout deadline",
            ) from e

    async def release(
        self,
        connection: Connection,
        *,
        discard: bool = False,
    ) -> None:
        """Return a healthy connection or close it rather than reusing it.

        Raises:
            RuntimeError: If the connection is not checked out from this pool.
        """
        async with self._condition:
            if connection not in self._checked_out:
                raise RuntimeError(
                    "connection is not checked out from this pool",
                )

            self._checked_out.remove(connection)
            close_connection = discard or self._closed or not connection.usable
            if close_connection:
                self._total -= 1
            else:
                self._idle.append(connection)

            self._condition.notify(1)

        if close_connection:
            await connection.close()

    async def execute(
        self,
        command: dict[str, Any],
        *,
        database: str,
        deadline: float | None,
    ) -> dict[str, Any]:
        """Execute one command using a checked-out connection.

        Returns:
            The MongoDB command reply.
        """
        lease = await self.acquire(deadline=deadline)
        discard = False
        try:
            return await lease.connection.command(
                command,
                database,
                deadline=deadline,
            )
        finally:
            discard = not lease.connection.usable
            await lease.release(discard=discard)

    async def close(self) -> None:
        """Close idle connections; checked-out ones are closed on return."""
        async with self._condition:
            if self._closed:
                return

            self._closed = True
            idle = tuple(self._idle)
            self._idle.clear()
            self._total -= len(idle)
            self._condition.notify_all()

        await asyncio.gather(
            *(connection.close() for connection in idle),
            return_exceptions=True,
        )

    async def __aenter__(self) -> Self:
        """Return this pool as an async context manager.

        Raises:
            PoolClosedError: if pool is closed.
        """
        if self._closed:
            raise PoolClosedError("connection pool is closed")

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the pool at context exit."""
        await self.close()
