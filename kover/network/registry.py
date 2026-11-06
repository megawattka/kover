"""Address-indexed server pools and their shared lifecycle."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ..exceptions import PoolClosedError
from ..execution.protocols import IPoolProvider
from .pool import ConnectionPool

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..execution.protocols import IServerPool
    from ..models.address import Address
    from .factory import ConnectionFactory


class PoolRegistry(IPoolProvider):
    """Lazily create and own one connection pool per server address."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        max_pool_size: int = 100,
        connection_timeout: float | None = 10.0,
        pool_factory: Callable[..., ConnectionPool] = ConnectionPool,
    ) -> None:
        if max_pool_size < 1:
            raise ValueError("max_pool_size must be positive")

        self._connection_factory = connection_factory
        self._max_pool_size = max_pool_size
        self._connection_timeout = connection_timeout
        self._pool_factory = pool_factory
        self._pools: dict[tuple[str, int], ConnectionPool] = {}
        self._closed = False

    def for_server(self, address: Address) -> IServerPool:
        """Return the existing pool or create one for ``address``.

        Raises:
            PoolClosedError: if pool is closed.
        """
        if self._closed:
            raise PoolClosedError("pool registry is closed")

        key = self._key(address)
        pool = self._pools.get(key)
        if pool is None:
            pool = self._pool_factory(
                address,
                lambda: self._connection_factory.create(address),
                max_pool_size=self._max_pool_size,
                connection_timeout=self._connection_timeout,
            )
            self._pools[key] = pool
        return pool

    @staticmethod
    def _key(address: Address) -> tuple[str, int]:
        return address.host.casefold(), address.port

    @property
    def pools(self) -> tuple[ConnectionPool, ...]:
        """A stable snapshot of currently registered pools."""
        return tuple(self._pools.values())

    @property
    def closed(self) -> bool:
        """Whether registry shutdown has begun."""
        return self._closed

    async def close(self) -> None:
        """Close every registered pool exactly once."""
        if self._closed:
            return

        self._closed = True
        pools = tuple(self._pools.values())
        self._pools.clear()

        await asyncio.gather(
            *(pool.close() for pool in pools),
            return_exceptions=True,
        )
