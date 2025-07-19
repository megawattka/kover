from __future__ import annotations

import asyncio
import os
import platform as sysinfo
import sys
from typing import TYPE_CHECKING, Literal

from .. import __version__
from ..codes import get_exception_name
from ..exceptions import OperationFailure
from ..models import HelloResult
from ..session import TxnState
from .serializer import Serializer

if TYPE_CHECKING:
    from ..session import Transaction
    from ..typings import COMPRESSION_T, DocumentT, xJsonT
    from .auth import AuthCredentials


class MongoSocket:
    """A socket for communicating with a MongoDB server."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.serializer = Serializer()
        self.lock = asyncio.Lock()
        self.compressor: Literal["zlib", "zstd", "snappy"] | None = None

    def __repr__(self) -> str:
        # this can return None?
        host, port = self.writer.get_extra_info(
            "peername", default=(None, None),
        )
        return f"<MongoSocket host={host} port={port}>"

    def set_compressor(self, compressor: Literal["zlib", "zstd", "snappy"]) -> None:
        """Sets the compressor. (no way!)."""
        self.compressor = compressor

    @classmethod
    async def make(
        cls,
        host: str,
        port: int,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> MongoSocket:
        """Create a MongoSocket instance."""
        loop = loop or asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=2 ** 16, loop=loop)
        protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
        transport, _ = await loop.create_connection(
            lambda: protocol, host, port,
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

    @staticmethod
    def get_hello_payload(
        compression: COMPRESSION_T | None = None,
    ) -> xJsonT:
        """Create a hello payload for the MongoDB server."""
        uname = sysinfo.uname()
        impl = sys.implementation
        if compression is None:
            compression = []
        platform = impl.name + " " + ".".join(map(str, impl.version))
        payload: xJsonT = {
            "hello": 1.0,
            "client": {
                "driver": {
                    "name": "Kover",
                    "version": __version__,
                },
                "os": {
                    "type": os.name,
                    "name": uname.system,
                    "architecture": uname.machine,
                    "version": uname.release,
                },
                "platform": platform,
            },
            "compression": compression,
        }
        return payload

    @staticmethod
    def _has_error_label(label: str, reply: xJsonT) -> bool:
        return label in reply.get("errorLabels", [])

    @staticmethod
    def _construct_exception(name: str) -> type[OperationFailure]:
        return type(name, (OperationFailure,), {
            "__module__": "kover.exceptions",
        })

    def _get_exception(self, reply: xJsonT) -> OperationFailure:
        write_errors = False
        if "writeErrors" in reply:
            write_errors = True
            reply = reply["writeErrors"][0]

        if "code" in reply:
            code: int = reply["code"]
            exc_name = get_exception_name(code=code)
            if exc_name is not None:
                error = reply["errmsg"] if not write_errors else reply
                exception = self._construct_exception(exc_name)
                return exception(code, error)

        if self._has_error_label("TransientTransactionError", reply=reply):
            exception = self._construct_exception(reply["codeName"])
            return exception(reply["code"], reply["errmsg"])

        return OperationFailure(-1, reply)

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
        rid, msg = self.serializer.get_message(doc, compressor=self.compressor)

        async with self.lock:
            await self.send(msg)
            if wait_response:
                header = await self.recv(16)
                length, op_code = self.serializer.verify_rid(header, rid)
                data = await self.recv(length - 16)  # exclude header
                reply = self.serializer.get_reply(data, op_code)
            else:  # cases like kover.shutdown()
                return {}

        if reply.get("ok") != 1.0 or reply.get("writeErrors") is not None:
            exc_value = self._get_exception(reply=reply)
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
    ) -> HelloResult:
        """Send a hello request to the MongoDB server and return the result."""
        payload = self.get_hello_payload(compression)
        if credentials is not None:
            credentials.apply_to(payload)

        hello = await self.request(payload)
        return HelloResult.model_validate(hello)
