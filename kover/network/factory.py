"""Construction and initialization of MongoDB connections."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from .connection import Connection
from .transport import Transport
from .wire.codec import CommandCodec
from .wire.compression import ZLIB_COMPRESSOR_ID, get_context_by_id

if TYPE_CHECKING:
    from elune import CodecOptions

    from ..models.address import Address
    from ..models.credentials import AuthCredentials


class ConnectionFactory:
    """Initialize application or dedicated monitoring connections."""

    def __init__(  # ruff: ignore[too-many-arguments] -- Independent connection setup components.
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

        """
        return await self._create(address, deadline, monitoring=False)

    async def create_monitor(
        self,
        address: Address,
        *,
        deadline: float,
    ) -> Connection:
        """Open a dedicated monitoring connection without authentication.

        Returns:
            A connection initialized with hello.
        """
        return await self._create(address, deadline, monitoring=True)

    async def _create(
        self,
        address: Address,
        deadline: float | None,
        *,
        monitoring: bool,
    ) -> Connection:
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
                codec_options=None if monitoring else self._codec_options,
            ),
        )

        try:
            async with asyncio.timeout_at(deadline):
                await connection.connect()
                await connection.hello(
                    self._compression,
                    None if monitoring else self._credentials,
                    self._application,
                )
        except Exception as exc:
            try:
                await connection.close()
            except (Exception, asyncio.CancelledError) as c_exc:  # ruff: ignore[blind-except]
                exc.add_note(
                    f"Connection cleanup also failed: {c_exc!r}",
                )
            raise
        except asyncio.CancelledError:
            await connection.close()
            raise

        return connection
