"""Construction and initialization of MongoDB connections."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from .connection import Connection
from .transport import Transport
from .wire.codec import CommandCodec
from .wire.compression import ZLIB_COMPRESSOR_ID, get_context_by_id

if TYPE_CHECKING:
    from bson import CodecOptions

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
        zlib_compression_level: int = -1,
        application: dict[str, Any] | None = None,
        credentials: AuthCredentials | None = None,
        codec_options: CodecOptions | None = None,
    ) -> None:
        self._tls = tls
        self._loop = loop
        self._compression = list(compression or ())
        get_context_by_id(
            ZLIB_COMPRESSOR_ID,
            zlib_compression_level=zlib_compression_level,
        )
        self._zlib_compression_level = zlib_compression_level
        self._application = (
            dict(application) if application is not None else None
        )
        self._credentials = credentials
        self._codec_options = codec_options

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
        connection = Connection(
            address,
            transport,
            codec=CommandCodec(
                zlib_compression_level=self._zlib_compression_level,
                codec_options=self._codec_options,
            ),
        )

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
