"""Asynchronous TCP/TLS byte transport."""

from __future__ import annotations

import asyncio
import ssl


class Transport:
    """Move opaque bytes over a TCP or TLS socket."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        tls: bool = False,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._tls = tls
        self._loop = loop
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._closed = False

    @property
    def connected(self) -> bool:
        """Whether the socket remains open locally."""
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        """Establish the TCP or TLS connection."""
        context = ssl.create_default_context() if self._tls else None
        self._reader, self._writer = await asyncio.open_connection(
            self.host,
            self.port,
            ssl=context,
            server_hostname=self.host if context is not None else None,
        )

    async def send(self, payload: bytes) -> None:
        """Write opaque bytes to the connected socket.

        Raises:
            OSError: if transport is not connected.
        """
        if self._writer is None or not self.connected:
            raise OSError("transport is not connected")

        self._writer.write(payload)
        await self._writer.drain()

    async def receive(self, size: int) -> bytes:
        """Read exactly ``size`` opaque bytes from the socket.

        Returns:
            bytes: received payload.

        Raises:
            OSError: if transport is not connected.
        """
        if self._reader is None or not self.connected:
            raise OSError("transport is not connected")

        return await self._reader.readexactly(size)

    async def close(self) -> None:
        """Close the writer and await transport shutdown."""
        if self._closed:
            return

        self._closed = True
        if self._writer is not None:
            self._writer.close()
            await self._writer.wait_closed()
