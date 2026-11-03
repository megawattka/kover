"""Connection pool and per-operation connection leases."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Self

from ..enums import PoolState, TxnState
from ..exceptions import (
    OperationFailure,
    PoolClosedError,
    PoolPausedError,
    PoolTimeoutError,
)
from ..models.network import Address, PoolStats
from ..read_preferences import ReadPreference, is_read_command
from ..typings import DEFAULT_MONGODB_PORT
from .codec import CommandCodec
from .connection import Connection
from .discovery import DiscoveryOptions, ServerDiscovery, ServerType
from .error_mapper import ErrorMapper
from .transport import Transport

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from types import TracebackType

    from ..session import Session
    from ..typings import DictT, DocumentT
    from ..uri_parser import ParsedUri
    from .auth import AuthCredentials


class ConnectionLease:
    """Exclusive ownership of one connection until release."""

    def __init__(self, pool: ConnectionPool, connection: Connection) -> None:
        self._pool = pool
        self._connection: Connection | None = connection
        self._released = False

    @property
    def connection(self) -> Connection:
        """Take the leased connection before release.

        Raises:
            RuntimeError: if lease already been released.
        """
        if self._connection is None:
            raise RuntimeError("connection lease has been released")
        return self._connection

    async def release(self, *, discard: bool = False) -> None:
        """Return or discard the connection idempotently."""
        if self._released:
            return

        self._released = True
        connection = self._connection
        self._connection = None

        if connection is not None:
            await self._pool.release(connection, discard=discard)

    async def __aenter__(self) -> Connection:
        return self.connection

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.release(discard=exc_type is not None)


class CommandReply(dict[str, Any]):  # ruff: ignore[subclass-builtin]
    """Command reply retaining its source server for cursor affinity."""

    def __init__(self, document: DictT, address: Address) -> None:
        super().__init__(document)
        self.server_address = address


class ConnectionPool:
    """Per-server pools with operation routing and no socket pins."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_MONGODB_PORT,
        *,
        credentials: AuthCredentials | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        compression: list[str] | None = None,
        tls: bool = False,
        application: DictT | None = None,
        max_pool_size: int = 100,
    ) -> None:
        if max_pool_size < 1:
            raise ValueError("max_pool_size must be positive")

        self.address = Address(host=host, port=port)
        self._credentials = credentials
        self._loop = loop
        self._compression = compression
        self._tls = tls
        self._application = application
        self._max_pool_size = max_pool_size
        self._connections: asyncio.Queue[Connection] = asyncio.Queue()
        self._connection_count = 0
        self._available = asyncio.Condition()
        self._closed = False
        self._state = PoolState.READY
        self._discovery: ServerDiscovery | None = None
        self._read_preference = ReadPreference()
        self._server_pools: dict[tuple[str, int], ConnectionPool] = {}
        self._selection_lock = asyncio.Lock()

    @classmethod
    async def from_parsed_uri(
        cls,
        parsed: ParsedUri,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> Self:
        """Build a pool after verifying a suitable server from all URI seeds.

        Returns:
            ConnectionPool itself.

        Raises:
            ValueError: If a requested topology option is unsupported.
        """
        if parsed.options.get("loadBalanced", False):
            raise ValueError("loadBalanced=true is not supported")

        tls = parsed.options.get("tls", False)
        compression = parsed.options.get("compressors")
        app_name = parsed.options.get("appname")
        application = {"name": app_name} if app_name is not None else None
        credentials = parsed.credentials
        return await cls.discover(
            [Address(host=host, port=port) for host, port in parsed.node_list],
            options=DiscoveryOptions(
                replica_set=parsed.options.get("replicaSet"),
                direct_connection=parsed.options.get(
                    "directConnection",
                    False,
                ),
                server_selection_timeout=parsed.options.get(
                    "serverSelectionTimeoutMS",
                    30.0,
                ),
                connect_timeout=(
                    parsed.options.get("connectTimeoutMS", 10.0) or None
                ),
                read_preference=ReadPreference(
                    mode=parsed.options.get("readPreference", "primary"),
                    tag_sets=(
                        tuple(parsed.options["readPreferenceTags"])
                        if "readPreferenceTags" in parsed.options
                        else None
                    ),
                    max_staleness_seconds=parsed.options.get(
                        "maxStalenessSeconds",
                        -1,
                    ),
                ),
                local_threshold=parsed.options.get("localThresholdMS", 15)
                / 1000,
            ),
            credentials=credentials,
            loop=loop,
            compression=compression,
            tls=tls,
            application=application,
            max_pool_size=parsed.options.get("maxPoolSize", 100),
        )

    @classmethod
    async def discover(
        cls,
        seeds: list[Address],
        *,
        options: DiscoveryOptions | None = None,
        credentials: AuthCredentials | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        compression: list[str] | None = None,
        tls: bool = False,
        application: DictT | None = None,
        max_pool_size: int = 100,
    ) -> Self:
        """Select a verified server and create its application pool.

        Returns:
            A single-server pool; discovery connections are already closed.

        Raises:
            ValueError: If max_pool_size is not positive.
        """
        if max_pool_size < 1:
            raise ValueError("max_pool_size must be positive")

        def factory(address: Address) -> Connection:
            probe_pool = cls(
                address.host,
                address.port,
                loop=loop,
                tls=tls,
                max_pool_size=max_pool_size,
            )
            return probe_pool._create_connection()

        discovery = ServerDiscovery(
            seeds,
            factory,
            options=options,
            compression=compression,
            credentials=credentials,
            application=application,
        )
        address = await discovery.select()
        pool = cls(
            address.host,
            address.port,
            credentials=credentials,
            loop=loop,
            compression=compression,
            tls=tls,
            application=application,
            max_pool_size=max_pool_size,
        )
        pool._discovery = discovery
        pool._read_preference = (options or DiscoveryOptions()).read_preference
        return pool

    def _pool_for(self, address: Address) -> ConnectionPool:
        if address == self.address:
            return self
        key = (address.host, address.port)
        if key not in self._server_pools:
            self._server_pools[key] = ConnectionPool(
                address.host,
                address.port,
                credentials=self._credentials,
                loop=self._loop,
                compression=self._compression,
                tls=self._tls,
                application=self._application,
                max_pool_size=self._max_pool_size,
            )
        return self._server_pools[key]

    async def _select_address(
        self,
        preference: ReadPreference,
        deadline: float | None,
    ) -> Address:
        discovery = self._discovery
        assert discovery is not None
        address = discovery.cached(preference)
        if address is not None:
            return address
        try:
            async with asyncio.timeout_at(deadline):
                await self._selection_lock.acquire()
        except TimeoutError as error:
            raise PoolTimeoutError(
                "server selection deadline expired",
            ) from error
        try:
            address = discovery.cached(preference)
            if address is None:
                address = await discovery.select(preference, deadline=deadline)
            return address
        finally:
            self._selection_lock.release()

    async def _route(  # ruff: ignore[complex-structure, too-many-branches]
        self,
        command: DictT,
        session: Session | None,
        preference: ReadPreference | None,
        address: Address | None,
        deadline: float | None,
    ) -> tuple[ConnectionPool, DictT]:
        if self._closed:
            raise PoolClosedError("request to a closed pool")
        if self._state is PoolState.PAUSED:
            raise PoolPausedError("connection pool is paused")
        preference = preference or self._read_preference
        reading = is_read_command(command)
        transactional = session is not None and (
            session.in_transaction or session.state is TxnState.COMMITTING
        )
        if transactional and reading and preference.mode != "primary":
            raise ValueError(
                "transaction reads require readPreference=primary",
            )
        effective = (
            preference if reading and not transactional else ReadPreference()
        )
        if next(iter(command), "") not in {"getMore", "killCursors"}:
            address = None
        if transactional and session is not None:
            address = session.pinned_server_address or address
        discovery = self._discovery
        if discovery is None:
            return self, command
        if address is None:
            address = await self._select_address(effective, deadline)
        if self._closed:
            raise PoolClosedError("request to a closed pool")
        if transactional and session is not None:
            session.pin_server(address)
        command = command.copy()
        command.pop("$readPreference", None)
        if reading:
            role = discovery.description(address).server_type
        else:
            role = ServerType.STANDALONE
        if role is not ServerType.STANDALONE:
            if (
                discovery.direct_connection
                and role is not ServerType.MONGOS
                and effective.mode == "primary"
                and not transactional
            ):
                effective = ReadPreference("primaryPreferred")
            if effective.mode != "primary":
                command["$readPreference"] = effective.to_dict()
        return self._pool_for(address), command

    def _create_connection(self) -> Connection:
        transport = Transport(
            self.address.host,
            self.address.port,
            loop=self._loop,
            tls=self._tls,
        )
        return Connection(
            self.address, transport, CommandCodec(), ErrorMapper(),
        )

    async def acquire(
        self,
        *,
        deadline: float | None = None,
    ) -> ConnectionLease:
        """Acquire one exclusive connection lease.

        Returns:
            ConnectionLease object.

        Raises:
            PoolClosedError: if pool is closed.
            PoolPausedError: if pool is paused.
            PoolTimeoutError: if connection checkout deadline expired.
        """
        async with self._available:
            while True:
                if self._closed or self._state is PoolState.CLOSED:
                    raise PoolClosedError("request to a closed pool")

                if self._state is PoolState.PAUSED:
                    raise PoolPausedError("connection pool is paused")

                if not self._connections.empty():
                    return ConnectionLease(
                        self, self._connections.get_nowait(),
                    )

                if self._connection_count < self._max_pool_size:
                    self._connection_count += 1
                    return ConnectionLease(self, self._create_connection())

                if deadline is None:
                    await self._available.wait()
                else:
                    timeout = max(
                        0.0,
                        deadline - asyncio.get_running_loop().time(),
                    )
                    try:
                        await asyncio.wait_for(self._available.wait(), timeout)
                    except TimeoutError as error:
                        raise PoolTimeoutError(
                            "connection checkout deadline expired",
                        ) from error

    async def release(
        self,
        connection: Connection,
        *,
        discard: bool = False,
    ) -> None:
        """Release connection back to pool."""
        async with self._available:
            close = discard or self._closed or not connection.usable
            if close:
                self._connection_count -= 1
            else:
                self._connections.put_nowait(connection)
            self._available.notify()

        if close:
            await connection.close()

    async def request(
        self,
        doc: DocumentT,
        *,
        db_name: str = "admin",
        session: Session | None = None,
        wait_response: bool = True,
        deadline: float | None = None,
        read_preference: ReadPreference | None = None,
        server_address: Address | None = None,
    ) -> DictT:
        """Route by read preference, preserving write and cursor affinity.

        Returns:
            The command response, including its source address as metadata.

        Raises:
            ValueError: If a transaction attempts a non-primary read.
        """
        if self._discovery is None:
            if (
                session is not None
                and session.in_transaction
                and is_read_command(dict(doc))
                and read_preference is not None
                and read_preference.mode != "primary"
            ):
                raise ValueError(
                    "transaction reads require readPreference=primary",
                )
            return await self._request_local(
                doc,
                db_name=db_name,
                session=session,
                wait_response=wait_response,
                deadline=deadline,
            )
        pool, command = await self._route(
            dict(doc),
            session,
            read_preference,
            server_address,
            deadline,
        )
        response = await pool._request_local(  # ruff: ignore[private-member-access]
            command,
            db_name=db_name,
            session=session,
            wait_response=wait_response,
            deadline=deadline,
        )
        return CommandReply(response, pool.address)

    async def _request_local(
        self,
        doc: DocumentT,
        *,
        db_name: str = "admin",
        session: Session | None = None,
        wait_response: bool = True,
        deadline: float | None = None,
    ) -> DictT:
        """Execute one command using an exclusively leased connection.

        Connect, perform hello and authenticate lazily when needed. Session
        metadata is applied to a shallow copy of the command, leaving the
        caller's document unchanged. The lease is released on success, failure
        or task cancellation; a session never retains the connection.

        Successful commands and server-reported OperationFailure errors allow
        connection reuse if it is still usable and the pool is open. Other
        failures, including cancellation, discard the connection because its
        protocol state may be uncertain. Commands are not retried here.

        Args:
            doc: Command document to send.
            db_name: Database against which to execute the command.
            session: Optional logical session providing command metadata.
            wait_response: Whether to read a response. If false, only send the
                command; server-side success is not verified.
            deadline: Absolute event-loop time for checkout and command I/O,
                or None for no deadline. It does not bound the initial
                connection, hello or authentication steps.

        Returns:
            The server response, or an empty dictionary if wait_response is
            false.

        Raises:
            OperationFailure: If MongoDB reports a command or write failure.

        Checkout propagates PoolClosedError, PoolPausedError or
        PoolTimeoutError. Connection setup, transport and protocol errors,
        as well as asyncio.CancelledError, propagate after lease cleanup.
        """
        lease = await self.acquire(deadline=deadline)
        connection = lease.connection
        discard = True
        try:  # ruff: ignore[too-many-statements-in-try-clause]
            if not connection.usable:
                await connection.connect()
                hello = await connection.hello(
                    self._compression, self._credentials, self._application,
                )
                if hello.requires_auth:
                    await connection.authorize(
                        hello.get_auth_mechanism(), self._credentials,
                    )
            command = {**doc}
            if session is not None:
                session.apply_to(command)

            if wait_response:
                response = await connection.command(
                    command,
                    db_name,
                    deadline=deadline,
                )
            else:
                await connection.fire_and_forget(
                    command,
                    db_name,
                    deadline=deadline,
                )
                response = {}

        except OperationFailure:
            discard = False
            raise
        else:
            discard = False
            return response
        finally:
            await lease.release(discard=discard)

    async def close(self) -> None:
        """Close the pool and all idle connections."""
        async with self._available:
            if self._closed:
                return
            self._closed = True
            self._state = PoolState.CLOSED
            connections: list[Connection] = []
            while not self._connections.empty():
                connections.append(self._connections.get_nowait())
            self._connection_count -= len(connections)
            self._available.notify_all()

        await asyncio.gather(
            *(c.close() for c in connections),
            *(pool.close() for pool in self._server_pools.values()),
            return_exceptions=True,
        )

    @property
    def closed(self) -> bool:
        """Whether the pool is closed."""
        return self._closed

    @property
    def state(self) -> PoolState:
        """Current pool lifecycle state."""
        return self._state

    def ready(self) -> None:
        """Resume a paused pool; a closed pool cannot be resumed.

        Raises:
            PoolClosedError: if pool is closed.
        """
        if self._state is PoolState.CLOSED:
            raise PoolClosedError("connection pool is closed")

        self._state = PoolState.READY

    async def clear(self) -> None:
        """Discard idle generation and pause new checkouts."""
        self._state = PoolState.PAUSED
        coros: list[Coroutine[None, None, None]] = []

        while not self._connections.empty():
            connection = self._connections.get_nowait()
            self._connection_count -= 1
            coros.append(connection.close())

        await asyncio.gather(*coros)

    def stats(self) -> PoolStats:
        """Return a snapshot of pool resource counters."""
        return PoolStats(
            state=self._state,
            idle=self._connections.qsize(),
            connecting=0,
            waiters=0,
            checked_out=self._connection_count - self._connections.qsize(),
        )
