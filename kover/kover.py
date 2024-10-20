from __future__ import annotations

import random
from typing import Optional, List

from .auth import AuthCredentials, Auth
from .typings import xJsonT
from .session import Session
from .socket import MongoSocket
from .database import Database

class Kover:
    def __init__(self, socket: MongoSocket, signature: Optional[bytes]) -> None:
        self.socket: MongoSocket = socket
        self.signature = signature

    def get_database(self, name: str) -> Database:
        return Database(name=name, socket=self.socket)
    
    def __getattr__(self, name: str) -> Database:
        return self.get_database(name=name)

    @classmethod
    async def make_client(
        cls,
        host: str = "127.0.0.1",
        port: int = 27017,
        credentials: Optional[AuthCredentials] = None
    ) -> Kover:
        socket = await MongoSocket.make(host, port)
        hello = await socket.hello(credentials=credentials)
        if hello.requires_auth and credentials:
            mechanism = random.choice(hello.mechanisms)
            signature = await Auth(socket).create(mechanism, credentials)
        else:
            signature = None
        return cls(socket, signature)

    async def refresh_sessions(self, sessions: List[Session]) -> bool:
        documents: List[xJsonT] = [x.document for x in sessions]
        request = await self.socket.request({"refreshSessions": documents})
        return request["ok"] == 1.0

    async def end_sessions(self, sessions: List[Session]) -> bool:
        documents: List[xJsonT] = [x.document for x in sessions]
        request = await self.socket.request({"endSessions": documents})
        return request["ok"] == 1.0

    async def start_session(self) -> Session:
        req = await self.socket.request({"startSession": 1.0})
        return Session(document=req["id"], socket=self.socket)
    
    async def build_info(self) -> xJsonT:
        request = await self.socket.request({"buildInfo": 1.0})
        return request
