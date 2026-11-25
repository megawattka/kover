"""Command routing and execution orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..exceptions import (
    NetworkError,
    OperationFailure,
    PoolTimeoutError,
    ProtocolError,
)
from ..models.read_preference import ReadPreference
from .context import CommandReply, OperationContext
from .preparation import prepare_command
from .protocols import ICommandExecutor
from .router import route_command

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..models.address import Address
    from ..models.concerns import WriteConcern
    from ..session import Session
    from ..topology.monitor import TopologyMonitor
    from ..topology.protocols import IServerSelector
    from .protocols import IPoolProvider, IServerPool


class CommandExecutor(ICommandExecutor):
    """Select a server, prepare metadata, and execute one command."""

    def __init__(
        self,
        *,
        selector: IServerSelector,
        pools: IPoolProvider,
        default_preference: ReadPreference | None = None,
        monitor: TopologyMonitor | None = None,
        pool_is_current: Callable[[Address, IServerPool], bool] | None = None,
    ) -> None:
        self._selector = selector
        self._pools = pools
        self._default_preference = default_preference or ReadPreference()
        self._monitor = monitor
        self._pool_is_current = pool_is_current

    async def execute(  # ruff: ignore[too-many-arguments] -- Implements the typed command execution contract.
        self,
        command: dict[str, Any],
        *,
        database: str = "admin",
        session: Session | None = None,
        read_preference: ReadPreference | None = None,
        server_address: Address | None = None,
        deadline: float | None = None,
        write_concern: WriteConcern | None = None,
    ) -> dict[str, Any]:
        """Route and execute a command without mutating the input document.

        Returns:
            The server reply.

        Raises:
            NetworkError: If communication with the selected server fails.
            OperationFailure: If the server rejects the command.
            PoolTimeoutError: If no connection is available before the
                connection checkout deadline.
            ProtocolError: If the server sends a malformed wire response.
            OSError: If a socket operation fails before network translation.
            TimeoutError: If server selection or command execution times out.
        """
        context = OperationContext(
            command=command,
            database=database,
            session=session,
            read_preference=read_preference,
            server_address=server_address,
            deadline=deadline,
            write_concern=write_concern,
        )
        address = await route_command(
            command,
            selector=self._selector,
            default_preference=self._default_preference,
            session=session,
            cursor_address=server_address,
            read_preference=read_preference,
            deadline=deadline,
        )
        prepared = prepare_command(
            context,
            address=address,
            selector=self._selector,
            default_preference=self._default_preference,
        )
        if prepared.transactional and session is not None:
            session.pin_server(address)

        pool = self._pools.for_server(address)
        try:
            reply = await pool.execute(
                prepared.document,
                database=context.database,
                deadline=deadline,
            )
        except (
            NetworkError,
            PoolTimeoutError,
            ProtocolError,
            TimeoutError,
            OSError,
        ) as exc:
            self._report_error(address, pool, exc)
            raise
        except OperationFailure as exc:
            if exc.is_server_selection_error:
                self._report_error(address, pool, exc)
            raise

        if prepared.starts_transaction and session is not None:
            session.mark_transaction_started()

        return CommandReply(reply, address)

    def _report_error(
        self,
        address: Address,
        pool: IServerPool,
        error: Exception,
    ) -> None:
        if self._monitor is None:
            self._selector.invalidate(address)
        elif not isinstance(error, PoolTimeoutError) and (
            self._pool_is_current is None
            or self._pool_is_current(address, pool)
        ):
            self._monitor.application_error(address, error)

    async def close(self) -> None:
        """Stop monitoring before closing the application server pools."""
        try:
            if self._monitor is not None:
                await self._monitor.stop()
        finally:
            await self._pools.close()
