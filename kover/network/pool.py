"""Connection pooling and initialization for MongoDB requests."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self

from ..typings import DEFAULT_MONGODB_PORT
from .transport import MongoTransport

if TYPE_CHECKING:
    from ..transaction import Transaction
    from ..typings import COMPRESSION_T, DocumentT, JsonT
    from ..uri_parser import ParsedUri
    from .auth import AuthCredentials


class ConnectionPool:
    """Lazily create and reuse MongoDB connections."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_MONGODB_PORT,
        *,
        credentials: AuthCredentials | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        compression: COMPRESSION_T | None = None,
        tls: bool = False,
        application: JsonT | None = None,
        max_pool_size: int = 100,
    ) -> None:
        if max_pool_size < 0:
            raise ValueError("max_pool_size must be non-negative")

        self._host = host
        self._port = port
        self._credentials = credentials
        self._loop = loop
        self._compression = compression
        self._tls = tls
        self._application = application
        self._max_pool_size = max_pool_size

        self._connections: asyncio.Queue[MongoTransport] = asyncio.Queue()
        self._connection_count = 0
        self._available = asyncio.Condition()
        self._closed = False

    @classmethod
    async def from_parsed_uri(
        cls,
        parsed: ParsedUri,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> Self:
        """Discover the primary and create a pool using parsed URI options.

        Returns:
            A pool targeting the primary MongoDB node.

        Raises:
            RuntimeError: if primary node resolution failed.
        """
        host, port = parsed.node_list[0]
        tls = parsed.options.get("tls", False)
        compression = parsed.options.get("compressors")
        application = {"name": parsed.options.get("appname")}
        credentials = parsed.credentials

        transport = MongoTransport(host, port, loop=loop, tls=tls)
        hello = None
        try:
            await transport.connect()
            hello = await transport.hello(
                compression, credentials, application)
        finally:
            await transport.close()

        assert hello is not None
        if not hello.is_primary:
            if hello.primary_node is None:
                raise RuntimeError("Primary node resolution failed")

            host, primary_port = hello.primary_node.rsplit(":", 1)
            port = int(primary_port)

        return cls(
            host,
            port,
            credentials=credentials,
            loop=loop,
            compression=compression,
            tls=tls,
            application=application,
            max_pool_size=parsed.options.get("maxPoolSize", 100),
        )

    def _create_connection(self) -> MongoTransport:
        return MongoTransport(
            self._host,
            self._port,
            loop=self._loop,
            tls=self._tls,
        )

    async def _acquire_connection(self) -> MongoTransport:
        async with self._available:
            while True:
                if self._closed:
                    raise RuntimeError("Request to a closed pool")

                if not self._connections.empty():
                    return self._connections.get_nowait()

                # max_pool_size=0 means unlimited.
                if (
                    self._max_pool_size == 0
                    or self._connection_count < self._max_pool_size
                ):
                    connection = self._create_connection()
                    self._connection_count += 1
                    return connection

                await self._available.wait()

    async def _release_connection(
        self,
        connection: MongoTransport,
        *,
        discard: bool = False,
    ) -> None:
        async with self._available:
            should_close = (
                discard
                or self._closed
                or not connection.is_connected
            )

            if should_close:
                self._connection_count -= 1
            else:
                self._connections.put_nowait(connection)

            self._available.notify()

        # Network I/O must not hold the pool's condition lock.
        if should_close:
            await connection.close()

    async def request(
        self,
        doc: DocumentT,
        *,
        db_name: str = "admin",
        transaction: Transaction | None = None,
        wait_response: bool = True,
    ) -> JsonT:
        """Send a request using a pooled connection.

        Returns:
            The server response.
        """
        connection = await self._acquire_connection()

        try:  # ruff: ignore[too-many-statements-in-try-clause]
            if not connection.is_connected:
                await connection.connect()

                hello = await connection.hello(
                    self._compression,
                    self._credentials,
                    self._application,
                )

                if hello.requires_auth:
                    await connection.authorize(
                        hello.get_auth_mechanism(),
                        credentials=self._credentials,
                    )

            response = await connection.request(
                doc,
                db_name=db_name,
                transaction=transaction,
                wait_response=wait_response,
            )

        except (Exception, asyncio.CancelledError) as err:
            try:
                await self._release_connection(
                    connection,
                    discard=True,
                )
            except (Exception, asyncio.CancelledError) as cerr:  # ruff: ignore[blind-except]
                err.add_note(
                    f"Connection cleanup also failed: {cerr!r}",
                )
            raise

        else:
            await self._release_connection(connection)
            return response

    async def close(self) -> None:
        """Close idle connections and reject new acquisitions.

        Checked-out connections are closed when returned to the pool.
        """
        async with self._available:
            if self._closed:
                return

            self._closed = True

            connections: list[MongoTransport] = []
            while not self._connections.empty():
                connections.append(self._connections.get_nowait())

            self._connection_count -= len(connections)
            self._available.notify_all()

        if connections:
            await asyncio.gather(
                *[connection.close() for connection in connections],
                return_exceptions=True,
            )

    @property
    def closed(self) -> bool:
        """Whether the pool is closed."""
        return self._closed
