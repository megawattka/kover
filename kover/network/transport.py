"""The transport layer for MongoDB connections."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import ssl
from typing import TYPE_CHECKING, Literal

from ..enums import TxnState
from ..helpers import classrepr
from ..models import HelloResult
from .auth import Auth
from .wirehelper import WireHelper

if TYPE_CHECKING:
    from ..session import Transaction
    from ..typings import COMPRESSION_T, DocumentT, xJsonT
    from .auth import AuthCredentials


@classrepr("_addr")
class MongoTransport:
    """A MongoDB transport for client reads/writes."""
    def __init__(
        self,
        host: str,
        port: int,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        tls: bool = False,
    ) -> None:
        self._compressor: Literal["zlib", "zstd", "snappy"] | None = None
        self._addr = (None, None)
        self._host = host
        self._port = port
        self._loop = loop
        self._tls = tls
        self._connected: bool = False
        self._helper = WireHelper()
        self._reader: asyncio.StreamReader = None  # type: ignore[assignment]
        self._writer: asyncio.StreamWriter = None  # type: ignore[assignment]

    async def connect(self) -> None:
        """Establish a connection to the MongoDB server."""
        if not self._connected:
            loop = self._loop or asyncio.get_running_loop()
            reader = asyncio.StreamReader(limit=2 ** 16, loop=loop)
            protocol = asyncio.StreamReaderProtocol(reader, loop=loop)

            ssl_ctx = ssl.create_default_context() if self._tls else None
            transport, _ = await loop.create_connection(
                lambda: protocol, self._host, self._port, ssl=ssl_ctx,
            )
            writer = asyncio.StreamWriter(transport, protocol, reader, loop)
            self._connected = True
            self._reader = reader
            self._writer = writer
            self._addr = self._writer.get_extra_info("peername", (None, None))

    @property
    def is_connected(self) -> bool:
        """Return True if we are conected False otherwise."""
        return self._connected

    def set_compressor(
        self,
        compressor: Literal["zlib", "zstd", "snappy"],
    ) -> None:
        """Sets the needed compressor type."""
        self._compressor = compressor

    def __del__(self) -> None:
        if self._connected:
            with suppress(RuntimeError):
                if not self._writer.is_closing():
                    self._writer.close()

    async def _send(self, msg: bytes) -> None:
        """Send a message to the MongoDB server.

        Raises:
            ConnectionError: If not connected to the server.
        """
        if not self._connected:
            raise ConnectionError("Not connected to the MongoDB server.")
        self._writer.write(msg)
        await self._writer.drain()

    async def _recv(self, size: int) -> bytes:
        """Receive a message from the MongoDB server.

        Returns:
            The received bytes from the server.

        Raises:
            ConnectionError: If not connected to the server.
        """
        # ... 13.05.2024 # https://stackoverflow.com/a/29068174
        if not self._connected:
            raise ConnectionError("Not connected to the MongoDB server.")
        return await self._reader.readexactly(size)

    async def request(
        self,
        doc: DocumentT,
        *,
        db_name: str = "admin",
        transaction: Transaction | None = None,
        wait_response: bool = True,
    ) -> xJsonT:
        """Send a request to the MongoDB server.

        Returns:
            The server's response as a dictionary.
        """
        doc = {**doc, "$db": db_name}  # order important
        if transaction is not None and transaction.is_active:
            transaction.apply_to(doc)
        rid, msg = self._helper.get_message(doc, compressor=self._compressor)

        await self._send(msg)
        if wait_response:
            header = await self._recv(16)
            length, op_code = self._helper.verify_rid(header, rid)
            data = await self._recv(length - 16)  # exclude header
            reply = self._helper.get_reply(data, op_code)
        else:  # cases like kover.shutdown()
            return {}

        if reply.get("ok") != 1.0 or reply.get("writeErrors") is not None:
            exc_value = self._helper.get_exception(reply=reply)
            if transaction is not None:
                transaction.end(TxnState.ABORTED, exc_value=exc_value)
            raise exc_value

        if transaction is not None:
            transaction.action_count += 1

        return reply

    async def hello(
        self,
        compression: COMPRESSION_T | None = None,
        credentials: AuthCredentials | None = None,
        application: xJsonT | None = None,
    ) -> HelloResult:
        """Send a hello request to the MongoDB server and return the result.

        Returns:
            An instance of HelloResult containing the server's response.
        """
        payload = self._helper.get_hello_payload(compression, application)

        if credentials is not None:
            credentials.apply_to(payload)

        document = await self.request(payload)
        hello = HelloResult.model_validate(document)

        if hello.compression:
            self.set_compressor(hello.compression[0])

        return hello

    async def authorize(
        self,
        mechanism: Literal["SCRAM-SHA-256", "SCRAM-SHA-1"] | None,
        credentials: AuthCredentials | None,
    ) -> bytes | None:
        """Perform authorization request and return a signature.

        Returns:
            The server signature after successful authentication,
            or None if no mechanism or credentials are provided.
        """
        if mechanism is not None and credentials is not None:
            return await Auth(self).create(
                mechanism=mechanism, credentials=credentials)
        return None

    async def close(self) -> None:
        """Close the connection to the MongoDB server."""
        if not self._connected:
            return
        self._writer.close()
        await self._writer.wait_closed()
