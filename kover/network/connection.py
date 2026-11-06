"""Command-level MongoDB connection used for discovery probes."""

from __future__ import annotations

import asyncio
from itertools import count
from typing import TYPE_CHECKING, Any

from .._utils.mappings import get_hello_payload
from ..exceptions import NetworkError
from .auth import Authenticator
from .wire.codec import CommandCodec
from .wire.error_mapper import ErrorMapper
from .wire.handshake import Handshake

if TYPE_CHECKING:
    from ..models.address import Address
    from ..models.credentials import AuthCredentials
    from ..models.hello import HelloResult
    from .transport import Transport


_MAX_MESSAGE_SIZE = 48 * 1024 * 1024


class Connection:
    """Perform MongoDB commands over a transport and wire codec."""

    def __init__(
        self,
        address: Address,
        transport: Transport,
        *,
        codec: CommandCodec | None = None,
        error_mapper: ErrorMapper | None = None,
    ) -> None:
        self.address = address
        self._transport = transport
        self._codec = codec or CommandCodec()
        self._error_mapper = error_mapper or ErrorMapper()
        self._handshake = Handshake(self.command)
        self._authenticator = Authenticator(self.command)
        self._request_ids = count(1)
        self._closed = False
        self._hello_result: HelloResult | None = None
        self._hello_round_trip_time = 0.0

    @property
    def hello_result(self) -> HelloResult | None:
        """Capabilities returned by the initial hello, if completed."""
        return self._hello_result

    @property
    def hello_round_trip_time(self) -> float:
        """Elapsed seconds spent waiting for the initial hello response."""
        return self._hello_round_trip_time

    @property
    def usable(self) -> bool:
        """Whether the transport is open for commands."""
        return not self._closed and self._transport.connected

    async def connect(self) -> None:
        """Open the underlying transport."""
        await self._transport.connect()

    async def close(self) -> None:
        """Invalidate the connection and abort its transport."""
        if self._closed:
            return

        self._closed = True
        await self._transport.close()

    async def command(
        self,
        document: dict[str, Any],
        database: str = "admin",
        *,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        """Exchange a command and validate its MongoDB response.

        Returns:
            Response from server.

        Raises:
            NetworkError: if connection is closed.
        """
        if self._closed:
            raise NetworkError("connection is closed")

        request_id = next(self._request_ids) % (2**31)
        request = self._codec.encode(
            document,
            database,
            request_id=request_id,
        )
        exchanged = False
        try:
            message = await self._exchange(request, deadline)
            reply = self._codec.decode(
                message,
                request_id=request_id,
            )
            exchanged = True
        finally:
            if not exchanged:
                await self.close()

        await self._error_mapper.check_reply(reply, with_writes=True)
        return reply

    async def _exchange(
        self,
        request: bytes,
        deadline: float | None,
    ) -> bytes:
        """Send a request and read one complete MongoDB wire message.

        Returns:
            Reply from mongodb server.
        """
        async with asyncio.timeout_at(deadline):
            return await self._send_and_receive(request)

    async def _send_and_receive(self, request: bytes) -> bytes:
        """Send one encoded request and receive one encoded response.

        Returns:
            Reply from mongodb server.
        """
        await self._transport.send(request)
        return await self._receive_message()

    async def _receive_message(self) -> bytes:
        """Read and validate a complete MongoDB wire message.

        Returns:
            Reply from mongodb server.

        Raises:
            ValueError: if protocol error occur.
        """
        prefix = await self._transport.receive(4)
        length = self._codec.frame_length(prefix)
        if length > _MAX_MESSAGE_SIZE:
            raise ValueError(f"invalid MongoDB message length: {length}")

        return prefix + await self._transport.receive(length - 4)

    async def hello(
        self,
        compression: list[str] | None = None,
        credentials: AuthCredentials | None = None,
        application: dict[str, Any] | None = None,
    ) -> HelloResult:
        """Send hello with client metadata and optional compression list.

        Returns:
            HelloResult model with server hello reply.
        """
        payload = get_hello_payload(compression, application)
        started = asyncio.get_running_loop().time()
        result = await self._handshake.hello(payload, credentials)
        self._hello_round_trip_time = (
            asyncio.get_running_loop().time() - started
        )

        if result.compression:
            compressor = result.compression[0]
            if compressor in {"zlib", "snappy", "zstd"}:
                self._codec.set_compressor(compressor)

        await self._authenticator.authenticate(result, credentials)
        self._hello_result = result
        return result
