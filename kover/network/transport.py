"""Low-level asynchronous byte transport."""

from __future__ import annotations

import asyncio
import ssl
from typing import Final

MIN_MESSAGE_LENGTH: Final[int] = 16


class Transport:
    """TCP/TLS byte exchange; it knows nothing about MongoDB commands."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        tls: bool = False,
        max_message_size: int = 48 * 1024 * 1024,
    ) -> None:
        self.host = host
        self.port = port
        self._loop = loop
        self._tls = tls
        self._max_message_size = max_message_size
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._closed = False

    @property
    def connected(self) -> bool:
        """Whether the socket is locally connected."""
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        """Open the socket once."""
        if self.connected:
            return

        loop = self._loop or asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=self._max_message_size, loop=loop)
        protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
        ssl_context = ssl.create_default_context() if self._tls else None

        transport, _ = await loop.create_connection(
            lambda: protocol, self.host, self.port, ssl=ssl_context,
        )
        self._reader = reader
        self._writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        self._closed = False

    async def exchange(
        self,
        request: bytes,
        *,
        deadline: float | None = None,
    ) -> bytes:
        """Send one request and read one complete response.

        Returns:
            message itself in bytes.

        Raises:
            ConnectionError: if transport is not connected.
        """
        if not self.connected or self._reader is None or self._writer is None:
            raise ConnectionError("transport is not connected")

        async def operation() -> bytes:
            if self._writer is None or self._reader is None:
                raise ConnectionError("transport is not connected")

            self._writer.write(request)
            await self._writer.drain()
            header = await self._reader.readexactly(4)
            length = int.from_bytes(header, "little", signed=True)

            if length < MIN_MESSAGE_LENGTH or length > self._max_message_size:
                raise ValueError(f"invalid MongoDB message length: {length}")

            return header + await self._reader.readexactly(length - 4)

        completed = False
        try:
            if deadline is None:
                response = await operation()
            else:
                timeout = max(
                    0.0, deadline - asyncio.get_running_loop().time(),
                )
                response = await asyncio.wait_for(operation(), timeout)
            completed = True
            return response
        finally:
            if not completed:
                self.abort()

    async def exchange_without_reply(
        self,
        request: bytes,
        *,
        deadline: float | None = None,
    ) -> None:
        """Send bytes without reading a response.

        Raises:
            ConnectionError: if transport is not connected.
        """
        if self._writer is None or not self.connected:
            raise ConnectionError("transport is not connected")

        async def operation(writer: asyncio.StreamWriter) -> None:
            writer.write(request)
            await writer.drain()

        sent = False
        try:
            if deadline is None:
                await operation(self._writer)
            else:
                timeout = max(
                    0.0,
                    deadline - asyncio.get_running_loop().time(),
                )
                await asyncio.wait_for(operation(self._writer), timeout)
            sent = True
        finally:
            if not sent:
                self.abort()

    def abort(self) -> None:
        """Synchronously close the socket after an uncertain exchange."""
        if self._closed:
            return
        self._closed = True
        if self._writer is not None and not self._writer.is_closing():
            self._writer.close()

    async def close(self) -> None:
        """Close the socket idempotently."""
        writer = self._writer
        self.abort()
        if writer is not None:
            await writer.wait_closed()
