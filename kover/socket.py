from __future__ import annotations

import platform as sysinfo
import sys
import os
import asyncio
from typing import Optional, Type, overload, Literal

from . import __version__
from .serializer import Serializer
from .typings import xJsonT, DocumentT, COMPRESSION_T
from .session import TxnState, Transaction
from .auth import AuthCredentials
from .models import HelloResult
from .exceptions import OperationFailure
from .codes import codes_to_exc_name


class MongoSocket:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.serializer = Serializer()
        self.lock = asyncio.Lock()

    def __repr__(self) -> str:
        # this can return None?
        host, port = self.writer.get_extra_info("peername") or (None, None)
        return f"<MongoSocket host={host} port={port}>"

    @classmethod
    async def make(
        cls,
        host: str,
        port: int,
        loop: Optional[asyncio.AbstractEventLoop] = None
    ) -> MongoSocket:
        loop = loop or asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=2 ** 16, loop=loop)
        protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
        transport, _ = await loop.create_connection(
            lambda: protocol, host, port
        )
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        return cls(reader, writer)

    async def send(self, msg: bytes) -> None:
        self.writer.write(msg)
        await self.writer.drain()

    async def recv(self, size: int) -> bytes:
        # ... 13.05.2024 # https://stackoverflow.com/a/29068174
        return await self.reader.readexactly(size)

    def get_hello_payload(
        self,
        compression: Optional[COMPRESSION_T]
    ) -> xJsonT:
        uname = sysinfo.uname()
        impl = sys.implementation
        platform = impl.name + " " + ".".join(map(str, impl.version))
        payload: xJsonT = {
            "hello": 1.0,
            "client": {
                "driver": {
                    "name": "Kover",
                    "version": __version__
                },
                "os": {
                    "type": os.name,
                    "name": uname.system,
                    "architecture": uname.machine,
                    "version": uname.release
                },
                "platform": platform
            }
        }
        if compression is not None:
            payload["compression"] = compression
        return payload

    def _has_error_label(self, label: str, reply: xJsonT) -> bool:
        return label in reply.get("errorLabels", [])

    def _construct_exception(self, name: str) -> Type[OperationFailure]:
        return type(name, (OperationFailure,), {
            "__module__": "kover.exceptions"
        })

    def _get_exception(self, reply: xJsonT) -> OperationFailure:
        write_errors = False
        if "writeErrors" in reply:
            write_errors = True
            reply = reply["writeErrors"][0]
        if "code" in reply:
            code: int = reply["code"]
            if code in codes_to_exc_name:
                exc_name = codes_to_exc_name[code]
                error = reply["errmsg"] if not write_errors else reply
                exception = self._construct_exception(exc_name)
                return exception(code, error)
        if self._has_error_label('TransientTransactionError', reply=reply):
            exception = self._construct_exception(reply["codeName"])
            return exception(reply["code"], reply["errmsg"])
        return OperationFailure(-1, reply)

    @overload
    async def request(
        self,
        doc: DocumentT,
        *,
        db_name: str = "admin",
        transaction: Optional[Transaction] = None,
        wait_response: Literal[True] = True
    ) -> xJsonT:
        ...

    @overload
    async def request(
        self,
        doc: DocumentT,
        *,
        db_name: str = "admin",
        transaction: Optional[Transaction] = None,
        wait_response: Literal[False] = False
    ) -> None:
        ...

    async def request(
        self,
        doc: DocumentT,
        *,
        db_name: str = "admin",
        transaction: Optional[Transaction] = None,
        wait_response: bool = True
    ) -> Optional[xJsonT]:
        doc = {**doc, "$db": db_name}
        if transaction is not None and transaction.is_active:
            transaction.apply_to(doc)
        rid, msg = self.serializer.get_message(doc)
        async with self.lock:
            await self.send(msg)
            if wait_response:
                header = await self.recv(16)
                length, op_code = self.serializer.verify_rid(header, rid)
                data = await self.recv(length - 16)  # exclude header
                reply = self.serializer.get_reply(data, op_code)
            else:
                return
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
        compression: Optional[COMPRESSION_T] = None,  # TODO: implement
        credentials: Optional[AuthCredentials] = None
    ) -> HelloResult:
        payload = self.get_hello_payload(compression)
        if credentials is not None:
            credentials.apply_to(payload)

        hello = await self.request(payload)

        return HelloResult(
            mechanisms=hello.get("saslSupportedMechs", []),
            local_time=hello["localTime"],
            connection_id=hello["connectionId"],
            read_only=hello["readOnly"],
            compression=hello.get("compression", [])
        )
