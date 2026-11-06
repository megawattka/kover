"""Construction and initialization of MongoDB connections."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from .connection import Connection
from .transport import Transport

if TYPE_CHECKING:
    from ..models.address import Address
    from ..models.credentials import AuthCredentials


class ConnectionFactory:
    """Create a connected, handshaken, and authenticated connection."""

    def __init__(
        self,
        *,
        tls: bool = False,
        loop: asyncio.AbstractEventLoop | None = None,
        compression: list[str] | None = None,
        application: dict[str, Any] | None = None,
        credentials: AuthCredentials | None = None,
    ) -> None:
        self._tls = tls
        self._loop = loop
        self._compression = list(compression or ())
        self._application = (
            dict(application) if application is not None else None
        )
        self._credentials = credentials

    async def create(
        self,
        address: Address,
        *,
        deadline: float | None = None,
    ) -> Connection:
        """Create and fully initialize a server connection.

        Close the connection if initialization fails.

        Returns:
            An open connection ready to send application commands.

        Raises:
            asyncio.CancelledError: If connection setup is cancelled.
        """
        transport = Transport(
            address.host,
            address.port,
            tls=self._tls,
            loop=self._loop,
        )
        connection = Connection(address, transport)

        try:
            async with asyncio.timeout_at(deadline):
                await connection.connect()
                await connection.hello(
                    self._compression,
                    self._credentials,
                    self._application,
                )
        except Exception as error:
            try:
                await connection.close()
            except (Exception, asyncio.CancelledError) as cleanup_error:  # ruff: ignore[blind-except]
                error.add_note(
                    f"Connection cleanup also failed: {cleanup_error!r}",
                )
            raise
        except asyncio.CancelledError:
            await connection.close()
            raise

        return connection
