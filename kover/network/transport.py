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
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self._helper = WireHelper()
        self.lock = asyncio.Lock()
        self.compressor: Literal["zlib", "zstd", "snappy"] | None = None
        self._addr = self.writer.get_extra_info("peername", (None, None))

    def set_compressor(
        self,
        compressor: Literal["zlib", "zstd", "snappy"],
    ) -> None:
        """Sets the needed compressor type."""
        self.compressor = compressor

    def __del__(self) -> None:
        with suppress(RuntimeError):
            if not self.writer.is_closing():
                self.writer.close()

    @classmethod
    async def make(
        cls,
        host: str,
        port: int,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        tls: bool = False,
    ) -> MongoTransport:
        """Create a MongoTransport instance."""
        loop = loop or asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=2 ** 16, loop=loop)
        protocol = asyncio.StreamReaderProtocol(reader, loop=loop)

        ssl_ctx = ssl.create_default_context() if tls else None
        transport, _ = await loop.create_connection(
            lambda: protocol, host, port, ssl=ssl_ctx,
        )
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        return cls(reader, writer)

    async def send(self, msg: bytes) -> None:
        """Send a message to the MongoDB server."""
        self.writer.write(msg)
        await self.writer.drain()

    async def recv(self, size: int) -> bytes:
        """Receive a message from the MongoDB server."""
        # ... 13.05.2024 # https://stackoverflow.com/a/29068174
        return await self.reader.readexactly(size)

    async def request(
        self,
        doc: DocumentT,
        *,
        db_name: str = "admin",
        transaction: Transaction | None = None,
        wait_response: bool = True,
    ) -> xJsonT:
        """Send a request to the MongoDB server."""
        doc = {**doc, "$db": db_name}  # order important
        if transaction is not None and transaction.is_active:
            transaction.apply_to(doc)
        rid, msg = self._helper.get_message(doc, compressor=self.compressor)

        async with self.lock:
            await self.send(msg)
            if wait_response:
                header = await self.recv(16)
                length, op_code = self._helper.verify_rid(header, rid)
                data = await self.recv(length - 16)  # exclude header
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
        """Send a hello request to the MongoDB server and return the result."""
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
        """Perform authorization request and return a signature."""
        if mechanism is not None and credentials is not None:
            return await Auth(self).create(
                mechanism=mechanism, credentials=credentials)
        return None
