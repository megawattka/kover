from __future__ import annotations

import random
from typing import Optional, List

from .auth import AuthCredentials, Auth
from .typings import xJsonT
from .session import Session
from .socket import MongoSocket
from .database import Database
from .models import BuildInfo

class Kover:
    def __init__(self, socket: MongoSocket, signature: Optional[bytes]) -> None:
        self.socket: MongoSocket = socket
        self.signature = signature

    def get_database(self, name: str) -> Database:
        return Database(name=name, client=self)
    
    def __getattr__(self, name: str) -> Database:
        return self.get_database(name=name)
    
    def _filter_document_values(self, doc: xJsonT) -> xJsonT:
        return {k: v for k, v in doc.items() if v is not None}
    
    @classmethod
    async def make_client(
        cls,
        host: str = "127.0.0.1",
        port: int = 27017,
        credentials: Optional[AuthCredentials] = None
    ) -> Kover:
        socket = await MongoSocket.make(host, port)
        hello = await socket._hello(credentials=credentials)
        if hello.requires_auth and credentials:
            mechanism = random.choice(hello.mechanisms)
            signature = await Auth(socket).create(mechanism, credentials)
        else:
            signature = None
        return cls(socket, signature)

    async def refresh_sessions(self, sessions: List[Session]) -> None:
        documents: List[xJsonT] = [x.document for x in sessions]
        await self.socket.request({"refreshSessions": documents})

    async def end_sessions(self, sessions: List[Session]) -> None:
        documents: List[xJsonT] = [x.document for x in sessions]
        await self.socket.request({"endSessions": documents})

    async def start_session(self) -> Session:
        req = await self.socket.request({"startSession": 1.0})
        return Session(document=req["id"], socket=self.socket)
    
    async def build_info(self) -> BuildInfo:
        request = await self.socket.request({"buildInfo": 1.0})
        return BuildInfo(
            version=request["version"],
            git_version=request["gitVersion"],
            allocator=request["allocator"],
            js_engine=request["javascriptEngine"],
            version_array=request["versionArray"],
            openssl=request["openssl"]["running"],
            debug=request["debug"],
            max_bson_obj_size=request["maxBsonObjectSize"],
            storage_engines=request["storageEngines"]
        )
    
    async def logout(self):
        await self.socket.request({"logout": 1.0})

    async def list_database_names(self) -> List[str]:
        command = {"listDatabases": 1.0, "nameOnly": True}
        request = await self.socket.request(command)
        return [x["name"] for x in request["databases"]]
