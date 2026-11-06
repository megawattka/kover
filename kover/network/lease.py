"""Exclusive checkout lease for a pooled connection."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import TracebackType

    from .connection import Connection
    from .pool import ConnectionPool


class ConnectionLease:
    """Own one connection until released back to its originating pool."""

    def __init__(self, pool: ConnectionPool, connection: Connection) -> None:
        self._pool = pool
        self._connection: Connection | None = connection
        self._released = False

    @property
    def connection(self) -> Connection:
        """The exclusively checked-out connection.

        Raises:
            RuntimeError: If this lease has already been released.
        """
        if self._connection is None:
            raise RuntimeError("connection lease has been released")
        return self._connection

    @property
    def released(self) -> bool:
        """Whether this lease has relinquished its connection."""
        return self._released

    async def release(self, *, discard: bool = False) -> None:
        """Return the connection or discard it; repeated calls are harmless."""
        if self._released:
            return
        self._released = True
        connection = self._connection
        self._connection = None
        if connection is not None:
            await self._pool.release(connection, discard=discard)

    async def __aenter__(self) -> Connection:
        """Return the leased connection."""
        return self.connection

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release, discarding the connection when the body raised."""
        await self.release(discard=exc_type is not None)
