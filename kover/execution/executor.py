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
    from ..models.address import Address
    from ..models.concerns import WriteConcern
    from ..session import Session
    from ..topology.protocols import IServerSelector
    from .protocols import IPoolProvider


class CommandExecutor(ICommandExecutor):
    """Select a server, prepare metadata, and execute one command."""

    def __init__(
        self,
        *,
        selector: IServerSelector,
        pools: IPoolProvider,
        default_preference: ReadPreference | None = None,
    ) -> None:
        self._selector = selector
        self._pools = pools
        self._default_preference = default_preference or ReadPreference()

    async def execute(
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

        try:
            reply = await self._pools.for_server(address).execute(
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
        ):
            self._selector.invalidate(address)
            raise
        except OperationFailure as error:
            if error.is_server_selection_error:
                self._selector.invalidate(address)
            raise

        if prepared.starts_transaction and session is not None:
            session.mark_transaction_started()

        return CommandReply(reply, address)

    async def close(self) -> None:
        """Close all server pools owned by the provider."""
        await self._pools.close()
