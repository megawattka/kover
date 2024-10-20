from __future__ import annotations

import json
import pathlib
import sys
import os
import asyncio
from typing import List, Union, Optional, NoReturn

from .serializer import Serializer
from .typings import xJsonT, DocumentT, COMPRESSION_T
from .session import _TxnState, Transaction
from .auth import AuthCredentials
from .models import HelloResult

class MongoSocket:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with pathlib.Path(__file__).parent.joinpath("codes.json").open("r") as fp:
            self.codes = json.load(fp)
        self.reader = reader
        self.writer = writer
        self.serializer = Serializer()
        self.lock = asyncio.Lock()

    @classmethod
    async def make(cls, host: str, port: int) -> MongoSocket:
        reader, writer = await asyncio.open_connection(host, port)
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
                    "name": "amongo", 
                    "version": "0.3.2"
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
    
    def _raise_exception(self, reply: xJsonT) -> NoReturn:
        write_errors = False
        if "writeErrors" in reply:
            write_errors = True
            reply = reply["writeErrors"][0]
        if "code" in reply:
            exc_name = self.codes[str(reply["code"])]
            error = reply["errmsg"] if not write_errors else reply
            exception = type(exc_name, (Exception,), {"__module__": "kover.exceptions"})
            raise exception(error)
        raise Exception(reply)
    
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
            if transaction is not None:
                transaction.end(_TxnState.ABORTED)
            self._raise_exception(reply)
        return reply

    async def _hello(
        self,
        compression: Optional[COMPRESSION_T] = None, # TODO
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