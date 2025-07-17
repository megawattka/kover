from __future__ import annotations

import json
import random
from typing import TYPE_CHECKING, Literal

from typing_extensions import Self

from .database import Database
from .models import BuildInfo
from .network import Auth, MongoSocket
from .session import Session
from .utils import filter_non_null, maybe_to_dict

if TYPE_CHECKING:
    import asyncio

    from .models import ReplicaSetConfig
    from .network import AuthCredentials
    from .typings import xJsonT


class Kover:
    """Kover client for interacting with a MongoDB server.

    Attributes:
    ----------
    socket : MongoSocket
        The underlying socket connection to the MongoDB server.
    signature : bytes | None
        The authentication signature, if authenticated.

    Methods:
    -------
    close() -> None
        Close the underlying socket connection.
    get_database(name: str) -> Database
        Get a Database instance for the specified database name.
    make_client(...)
        Create and return a new Kover client instance.
    refresh_sessions(sessions: list[Session]) -> None
        Refresh the provided list of sessions.
    end_sessions(sessions: list[Session]) -> None
        End the provided list of sessions.
    start_session() -> Session
        Start a new session.
    build_info() -> BuildInfo
        Retrieve build information from the MongoDB server.
    logout() -> None
        Log out the current user session.
    list_database_names() -> list[str]
        Retrieve the names of all databases on the MongoDB server.
    drop_database(name: str) -> None
        Drop the specified database from the MongoDB server.
    replica_set_initiate(config: xJsonT | None = None) -> None
        Initiate a replica set with the provided configuration.
    get_replica_set_status() -> xJsonT
        Retrieve the status of the replica set.
    shutdown(...)
        Shut down the MongoDB server.
    get_commandline() -> list[str]
        Retrieve the command line arguments used to start the MongoDB server.
    get_log(parameter: Literal["global", "startupWarnings"] = "startupWarnings") -> list[xJsonT]
        Retrieve log entries from the MongoDB server.
    rename_collection(...)
        Rename a collection in the MongoDB server.
    set_user_write_block_mode(param: bool) -> None
        Set the user write block mode on the MongoDB server.
    fsync(...)
        Flush all pending writes to disk and optionally lock the database.
    fsync_unlock(comment: str | None = None) -> None
        Unlock the database after a previous fsync lock operation.
    """  # noqa: E501

    def __init__(
        self,
        socket: MongoSocket,
        signature: bytes | None,
    ) -> None:
        self.socket: MongoSocket = socket
        self.signature = signature

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        if self.signature is not None:
            await self.logout()
        await self.close()
        return True

    def __repr__(self) -> str:
        return f"<Kover signature={self.signature} socket={self.socket}>"

    async def close(self) -> None:
        """Close the underlying socket connection.

        This method closes the socket writer and waits until the connection is fully closed.
        """  # noqa: E501
        self.socket.writer.close()
        await self.socket.writer.wait_closed()

    def get_database(self, name: str) -> Database:
        """Get a Database instance for the specified database name.

        Parameters:
        ----------
        name : str
            The name of the database to retrieve.

        Returns:
        -------
        Database
            An instance of the Database class for the given name.
        """
        return Database(name=name, client=self)

    def __getattr__(self, name: str) -> Database:
        return self.get_database(name=name)

    @classmethod
    async def make_client(
        cls,
        host: str = "127.0.0.1",
        port: int = 27017,
        credentials: AuthCredentials | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> Kover:
        """Create and return a new Kover client instance.

        Parameters:
        ----------
        host : str, optional
            The hostname of the MongoDB server, by default "127.0.0.1".
        port : int, optional
            The port number of the MongoDB server, by default 27017.
        credentials : AuthCredentials or None, optional
            Authentication credentials, if required.
        loop : asyncio.AbstractEventLoop or None, optional
            The event loop to use for asynchronous operations.

        Returns:
        -------
        Kover
            An instance of the Kover client.
        """
        socket = await MongoSocket.make(host, port, loop=loop)
        hello = await socket.hello(credentials=credentials)
        if hello.requires_auth and credentials:
            mechanism = random.choice(hello.sasl_supported_mechs or [])  # noqa: S311
            signature = await Auth(socket).create(mechanism, credentials)
        else:
            signature = None
        return cls(socket, signature)

    async def refresh_sessions(self, sessions: list[Session]) -> None:
        """Refresh the provided list of sessions.

        Parameters:
        ----------
        sessions : list[Session]
            A list of Session objects to be refreshed.
        """
        documents: list[xJsonT] = [x.document for x in sessions]
        await self.socket.request({"refreshSessions": documents})

    async def end_sessions(self, sessions: list[Session]) -> None:
        """End the provided list of sessions.

        Parameters:
        ----------
        sessions : list[Session]
            A list of Session objects to be ended.
        """
        documents: list[xJsonT] = [x.document for x in sessions]
        await self.socket.request({"endSessions": documents})

    async def start_session(self) -> Session:
        """Start a new session.

        Returns:
        -------
        Session
            An instance of the Session class representing the started session.
        """
        req = await self.socket.request({"startSession": 1.0})
        return Session(document=req["id"], socket=self.socket)

    async def build_info(self) -> BuildInfo:
        """Retrieve build information from the MongoDB server.

        Returns:
        -------
        BuildInfo
            An instance of BuildInfo containing server build details.
        """
        request = await self.socket.request({"buildInfo": 1.0})
        return BuildInfo(
            version=request["version"],
            git_version=request["gitVersion"],
            allocator=request["allocator"],
            javascript_engine=request["javascriptEngine"],
            version_array=request["versionArray"],
            openssl=request["openssl"]["running"],
            debug=request["debug"],
            max_bson_object_size=request["maxBsonObjectSize"],
            storage_engines=request["storageEngines"],
        )

    async def logout(self) -> None:
        """Log out the current user session.

        This method sends a logout request to the server to terminate the current authenticated session.
        """  # noqa: E501
        await self.socket.request({"logout": 1.0})

    async def list_database_names(self) -> list[str]:
        """Retrieve the names of all databases on the MongoDB server.

        Returns:
        -------
        list[str]
            A list containing the names of all databases.
        """
        command: xJsonT = {
            "listDatabases": 1.0,
            "nameOnly": True  # noqa: COM812
        }
        request = await self.socket.request(command)
        return [x["name"] for x in request["databases"]]

    async def drop_database(self, name: str) -> None:
        """Drop the specified database from the MongoDB server.

        Parameters:
        ----------
        name : str
            The name of the database to drop.
        """
        await self.socket.request({"dropDatabase": 1.0}, db_name=name)

    # https://www.mongodb.com/docs/manual/reference/command/replSetInitiate/
    async def replica_set_initiate(
        self,
        config: ReplicaSetConfig | None = None,
    ) -> None:
        """Initiate a replica set with the provided configuration.

        Parameters:
        ----------
        config : ReplicaSetConfig or None, optional
            The configuration document for the replica set. If None,
            default configuration is used.

        Returns:
        -------
        None
        """
        document = maybe_to_dict(config) or {}
        await self.socket.request({"replSetInitiate": document})

    # https://www.mongodb.com/docs/manual/reference/command/replSetReconfig/
    async def replica_set_reconfig(
        self,
        config: ReplicaSetConfig,
        force: bool = False,
        max_time_ms: int | None = None,
    ) -> None:
        """Perform Reconfiguration of a replica set.

        Parameters:
        ----------
        config : ReplicaSetConfig
            The configuration document for the replica set.

        Returns:
        -------
        None
        """
        document: xJsonT = filter_non_null({
            "replSetReconfig": maybe_to_dict(config) or {},
            "force": force,
            "maxTimeMS": max_time_ms,
        })
        await self.socket.request(document)

    # https://www.mongodb.com/docs/manual/reference/command/replSetGetStatus/
    async def get_replica_set_status(self) -> xJsonT:
        """Retrieve the status of the replica set.

        Returns:
        -------
        xJsonT
            A JSON document containing the replica set status information.
        """
        return await self.socket.request({"replSetGetStatus": 1.0})

    # https://www.mongodb.com/docs/manual/reference/command/shutdown/
    async def shutdown(
        self,
        force: bool = False,
        timeout: int | None = None,
        comment: str | None = None,
    ) -> None:
        """Shut down the MongoDB server.

        Parameters:
        ----------
        force : bool, optional
            Whether to force the shutdown, by default False.
        timeout : int or None, optional
            Timeout in seconds before shutdown, by default None.
        comment : str or None, optional
            Optional comment for the shutdown command.

        Returns:
        -------
        None
        """
        command = filter_non_null({
            "shutdown": 1.0,
            "force": force,
            "timeoutSecs": timeout,
            "comment": comment,
        })
        await self.socket.request(command, wait_response=False)

    # https://www.mongodb.com/docs/manual/reference/command/getCmdLineOpts/
    async def get_commandline(self) -> list[str]:
        """Retrieve the command line args used to start the MongoDB server.

        Returns:
        -------
        list[str]
            A list of command line arguments.
        """
        r = await self.socket.request({"getCmdLineOpts": 1.0})
        return r["argv"]

    # https://www.mongodb.com/docs/manual/reference/command/getLog/#getlog
    async def get_log(
        self,
        parameter: Literal["global", "startupWarnings"] = "startupWarnings",
    ) -> list[xJsonT]:
        """Retrieve log entries from the MongoDB server.

        Parameters:
        ----------
        parameter : Literal["global", "startupWarnings"], optional
            The log type to retrieve, defaults to "startupWarnings".

        Returns:
        -------
        list[xJsonT]
            A list of log entries as JSON objects.
        """
        r = await self.socket.request({"getLog": parameter})
        return [
            json.loads(info) for info in r["log"]
        ]

    # https://www.mongodb.com/docs/manual/reference/command/renameCollection/
    async def rename_collection(
        self,
        target: str,
        new_name: str,
        drop_target: bool = False,
        comment: str | None = None,
    ) -> None:
        """Rename a collection in the MongoDB server.

        Parameters:
        ----------
        target : str
            The full name of the source collection to rename.
        new_name : str
            The new name for the collection.
        drop_target : bool, optional
            Whether to drop the target collection if it exists, by default False.
        comment : str or None, optional
            Optional comment for the rename operation.

        Returns:
        -------
        None
        """  # noqa: E501
        command = filter_non_null({
            "renameCollection": target,
            "to": new_name,
            "dropTarget": drop_target,
            "comment": comment,
        })
        await self.socket.request(command)

    # https://www.mongodb.com/docs/manual/reference/command/setUserWriteBlockMode/
    async def set_user_write_block_mode(self, param: bool) -> None:
        """Set the user write block mode on the MongoDB server.

        Parameters:
        ----------
        param : bool
            Blocks writes on a cluster when set to true. To enable writes on a cluster, set global: false.

        Returns:
        -------
        None
        """  # noqa: E501
        await self.socket.request({
            "setUserWriteBlockMode": 1.0,
            "global": param,
        })

    # https://www.mongodb.com/docs/manual/reference/command/fsync/
    async def fsync(
        self,
        timeout: int = 90000,
        lock: bool = True,
        comment: str | None = None,
    ) -> None:
        """Flush all pending writes to disk and optionally lock the database.

        Parameters:
        ----------
        timeout : int, optional
            Timeout in milliseconds for acquiring the fsync lock, by default 90000.
        lock : bool, optional
            Whether to lock the database after flushing, by default True.
        comment : str or None, optional
            Optional comment for the fsync operation.

        Returns:
        -------
        None
        """  # noqa: E501
        command = filter_non_null({
            "fsync": 1.0,
            "fsyncLockAcquisitionTimeoutMillis": timeout,
            "lock": lock,
            "comment": comment,
        })
        await self.socket.request(command)

    # https://www.mongodb.com/docs/manual/reference/command/fsyncUnlock/
    async def fsync_unlock(self, comment: str | None = None) -> None:
        """Unlock the database after a previous fsync lock operation.

        Parameters:
        ----------
        comment : str or None, optional
            Optional comment for the fsync unlock operation.

        Returns:
        -------
        None
        """
        command = filter_non_null({
            "fsyncUnlock": 1.0,
            "comment": comment,
        })
        await self.socket.request(command)
