from __future__ import annotations

import json
import pathlib
import sys
import os
import asyncio
from typing import Optional, Type

from . import __version__
from .serializer import Serializer
from .typings import xJsonT, DocumentT, COMPRESSION_T
from .session import _TxnState, Transaction
from .auth import AuthCredentials
from .models import HelloResult
from .exceptions import OperationFailure

class MongoSocket:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with pathlib.Path(__file__).parent.joinpath("codes.json").open("r") as fp:
            self.codes = json.load(fp)
        self.reader = reader
        self.writer = writer
        self.serializer = Serializer()
        self.lock = asyncio.Lock()

    @classmethod
    async def make(
        cls, 
        host: str, 
        port: int,
        loop: Optional[asyncio.AbstractEventLoop] = None
    ) -> MongoSocket:
        if loop is None:
            loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=2 ** 16, loop=loop)
        protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
        transport, _ = await loop.create_connection(lambda: protocol, host, port)
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        return cls(reader, writer)

    async def send(self, msg: bytes) -> None:
        self.writer.write(msg)
        await self.writer.drain()

    async def recv(self, size: int) -> bytes:
        return await self.reader.readexactly(size) # ... 13.05.2024 # https://stackoverflow.com/a/29068174

    def get_hello_payload(self, compression: Optional[COMPRESSION_T]) -> xJsonT:
        uname = os.uname() # TODO: Windows
        impl = sys.implementation
        platform = impl.name + " " + ".".join(map(str, impl.version))
        payload = {
            "hello": 1.0, 
            "client": {
                "driver": {
                    "name": "Kover", 
                    "version": __version__
                }, 
                "os": {
                    "type": os.name, 
                    "name": uname.sysname, 
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
        return type(name, (OperationFailure,), {"__module__": "kover.exceptions"})
    
    def _get_exception(self, reply: xJsonT) -> OperationFailure:
        write_errors = False
        if "writeErrors" in reply:
            write_errors = True
            reply = reply["writeErrors"][0]
        if "code" in reply:
            code = str(reply["code"])
            if code in self.codes:
                exc_name = self.codes[code]
                error = reply["errmsg"] if not write_errors else reply
                exception = self._construct_exception(exc_name)
                return exception(reply["code"], error)
        if self._has_error_label('TransientTransactionError', reply=reply):
            exception = self._construct_exception(reply["codeName"])
            return exception(reply["code"], reply["errmsg"])
        return OperationFailure(-1, reply)
    
    async def request(
        self,
        doc: DocumentT,
        *,
        db_name: str = "admin",
        transaction: Optional[Transaction] = None
    ) -> xJsonT:
        doc = doc.copy(); doc.setdefault("$db", db_name)
        if transaction is not None and transaction.is_active:
            transaction.apply_to(doc)
        rid, msg = self.serializer.get_message(doc)
        async with self.lock:
            await self.send(msg)
            header = await self.recv(16)
            length, op_code = self.serializer.verify_rid(header, rid)
            data = await self.recv(length - 16) # exclude header
            reply = self.serializer.get_reply(data, op_code)
        if reply.get("ok") != 1.0 or reply.get("writeErrors") is not None:
            exc_value = self._get_exception(reply=reply)
            if transaction is not None:
                transaction.end(_TxnState.ABORTED, exc_value=exc_value)
            raise exc_value
        if transaction is not None:
            transaction.action_count += 1
        return reply

    async def _hello(
        self,
        compression: Optional[COMPRESSION_T] = None, # TODO: implement
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