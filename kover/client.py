from __future__ import annotations

import json
import asyncio
import random
from typing import Optional, List, Any, Literal
from typing_extensions import Self

from .auth import AuthCredentials, Auth
from .typings import xJsonT
from .session import Session
from .socket import MongoSocket
from .database import Database
from .models import BuildInfo
from .schema import filter_non_null


class Kover:
    def __init__(
        self,
        socket: MongoSocket,
        signature: Optional[bytes]
    ) -> None:
        self.socket: MongoSocket = socket
        self.signature = signature

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: tuple[Any]) -> bool:
        if self.signature is not None:
            await self.logout()
        await self.close()
        return True

    async def close(self) -> None:
        self.socket.writer.close()
        await self.socket.writer.wait_closed()

    def get_database(self, name: str) -> Database:
        return Database(name=name, client=self)

    def __getattr__(self, name: str) -> Database:
        return self.get_database(name=name)

    @classmethod
    async def make_client(
        cls,
        host: str = "127.0.0.1",
        port: int = 27017,
        credentials: Optional[AuthCredentials] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None
    ) -> Kover:
        socket = await MongoSocket.make(host, port, loop=loop)
        hello = await socket.hello(credentials=credentials)
        if hello.requires_auth and credentials:
            mechanism = random.choice(hello.mechanisms or [])
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
        command: xJsonT = {
            "listDatabases": 1.0,
            "nameOnly": True
        }
        request = await self.socket.request(command)
        return [x["name"] for x in request["databases"]]

    async def drop_database(self, name: str) -> None:
        await self.socket.request({"dropDatabase": 1.0}, db_name=name)

    # https://www.mongodb.com/docs/manual/reference/command/replSetInitiate/
    async def replica_set_initiate(
        self,
        config: Optional[xJsonT] = None
    ) -> None:
        await self.socket.request({"replSetInitiate": config or {}})

    # https://www.mongodb.com/docs/manual/reference/command/replSetGetStatus/#mongodb-dbcommand-dbcmd.replSetGetStatus
    async def get_replica_set_status(self) -> xJsonT:
        return await self.socket.request({"replSetGetStatus": 1.0})

    # https://www.mongodb.com/docs/manual/reference/command/shutdown/
    async def shutdown(
        self,
        force: bool = False,
        timeout: Optional[int] = None,
        comment: Optional[str] = None
    ) -> None:
        command = filter_non_null({
            "shutdown": 1.0,
            "force": force,
            "timeoutSecs": timeout,
            "comment": comment
        })
        await self.socket.request(command, wait_response=False)

    # https://www.mongodb.com/docs/manual/reference/command/getCmdLineOpts/#getcmdlineopts
    async def get_commandline(self) -> list[str]:
        r = await self.socket.request({"getCmdLineOpts": 1.0})
        return r["argv"]

    # https://www.mongodb.com/docs/manual/reference/command/getLog/#getlog
    async def get_log(
        self,
        parameter: Literal["global", "startupWarnings"] = "startupWarnings"
    ) -> List[xJsonT]:
        r = await self.socket.request({"getLog": parameter})
        return [
            json.loads(info) for info in r["log"]
        ]

    # https://www.mongodb.com/docs/manual/reference/command/renameCollection/#renamecollection
    async def rename_collection(
        self,
        target: str,
        new_name: str,
        drop_target: bool = False,
        comment: Optional[str] = None
    ) -> None:
        command = filter_non_null({
            "renameCollection": target,
            "to": new_name,
            "dropTarget": drop_target,
            "comment": comment
        })
        await self.socket.request(command)

    # https://www.mongodb.com/docs/manual/reference/command/setUserWriteBlockMode/#setuserwriteblockmode
    async def set_user_write_block_mode(self, param: bool) -> None:
        await self.socket.request({
            "setUserWriteBlockMode": 1.0,
            "global": param
        })

    # https://www.mongodb.com/docs/manual/reference/command/fsync/#fsync
    async def fsync(
        self,
        timeout: int = 90000,
        lock: bool = True,
        comment: Optional[str] = None
    ) -> None:
        command = filter_non_null({
            "fsync": 1.0,
            "fsyncLockAcquisitionTimeoutMillis": timeout,
            "lock": lock,
            "comment": comment
        })
        await self.socket.request(command)

    # https://www.mongodb.com/docs/manual/reference/command/fsyncUnlock/#fsyncunlock
    async def fsync_unlock(self, comment: Optional[str] = None) -> None:
        command = filter_non_null({
            "fsyncUnlock": 1.0,
            "comment": comment
        })
        await self.socket.request(command)
