from __future__ import annotations

import sys
import os
import asyncio
import warnings
from typing import List, Union, Optional

from .serializer import Serializer
from .typings import xJsonT, DocumentT, COMPRESSION_T
from .session import _TxnState, Transaction
from .auth import AuthCredentials
from .models import HelloResult

class MongoSocket:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
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

    def get_hello_payload(self) -> xJsonT:
        uname = os.uname() # TODO: Windows
        impl = sys.implementation
        platform = impl.name + " " + ".".join(map(str, impl.version))
        return {
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
            },
            "$db": "admin"
        }
    
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
            xJsonT = await self.recv(length - 16) # exclude header
            reply = self.serializer.get_reply(xJsonT, op_code)
        if reply.get("ok") != 1.0 or reply.get("writeErrors") is not None:
            if transaction is not None:
                transaction.end(_TxnState.ABORTED)
            raise Exception(reply)
        return reply

    async def hello(
        self,
        compression: Optional[COMPRESSION_T] = None, # TODO
        credentials: Optional[AuthCredentials] = None
    ) -> HelloResult:
        payload = self.get_hello_payload()

        if compression:
            payload["compression"] = compression
        if credentials:
            payload["saslSupportedMechs"] = f"{credentials.db_name}.{credentials.username}"
        
        hello = await self.request(payload)
        
        return HelloResult(
            mechanisms=hello.get("saslSupportedMechs", []),
            local_time=hello["localTime"],
            connection_id=hello["connectionId"],
            read_only=hello["readOnly"],
            compression=hello.get("compression", [])
        )

    async def create_user(
        self,
        username: str,
        password: str,
        roles: List[Union[xJsonT, str]],
        db_name: str = "admin",
        mechanisms: List[str] = ["SCRAM-SHA-1", "SCRAM-SHA-256"]
    ) -> bool:
        command = {
            "createUser": username, 
            "pwd": password, 
            "roles": roles, 
            "mechanisms": mechanisms
        }
        request = await self.request(command, db_name=db_name)
        return request["ok"] == 1.0

    async def drop_user(self, username: str, db_name: str) -> bool:
        req = await self.request({"dropUser": username}, db_name=db_name)
        return req["ok"] == 1.0

    async def drop_database(self, db_name: str) -> bool:
        request = await self.request({"dropDatabase": 1.0}, db_name=db_name)
        return request["ok"] == 1.0

    async def list_database_names(self) -> List[str]:
        command = {"listDatabases": 1.0, "nameOnly": True}
        request = await self.request(command)
        return [x["name"] for x in request["databases"]]

    async def grant_roles_to_user(self, username: str, roles: List[Union[str, xJsonT]]) -> bool:
        command = {"grantRolesToUser": username, "roles": roles}
        request = await self.request(command)
        return request["ok"] == 1.0

    async def list_users(self) -> List[xJsonT]:
        params = {"find": "system.users", "filter": {}}
        request = await self.request(params)
        return [x for x in request["cursor"]["firstBatch"]]