"""Kover Client Module."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal, Self

from kover.cursor import Cursor

from .database import Database
from .helpers import (
    classrepr,
    filter_non_null,
    maybe_to_dict,
    raw_decoder,
)
from .models import BuildInfo, ReadConcern, WriteConcern
from .network import ConnectionPool
from .session import Session
from .typings import DEFAULT_MONGODB_PORT
from .uri_parser import parse_uri

if TYPE_CHECKING:
    import asyncio

    from .models import ReplicaSetConfig
    from .network import AuthCredentials
    from .typings import CompressionT, DictT, DocumentT


_WRITE_CONCERN_COMMANDS = frozenset({
    "bulkWrite",
    "collMod",
    "create",
    "createIndexes",
    "delete",
    "drop",
    "dropAllUsersFromDatabase",
    "dropDatabase",
    "dropIndexes",
    "dropUser",
    "findAndModify",
    "insert",
    "renameCollection",
    "update",
})


@classrepr("_write_concern", "_pool")
class Kover:
    """Kover client for interacting with a MongoDB server."""

    def __init__(
        self,
        *,
        write_concern: WriteConcern | None = None,
        pool: ConnectionPool,
    ) -> None:
        if write_concern is None:
            self._write_concern = WriteConcern()
        else:
            self._write_concern = write_concern
        self._pool = pool

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        await self.close()
        return False

    @property
    def pool(self) -> ConnectionPool:
        """Acquire raw connection pool obj."""
        return self._pool

    async def close(self) -> None:
        """Release the resources owned by the client."""
        await self._pool.close()

    def get_database(self, name: str) -> Database:
        """Get a Database instance for the specified database name.

        Parameters:
            name : The name of the database to retrieve.

        Returns:
            An instance of the Database class for the given name.
        """
        return Database(name=name, client=self)

    def __getattr__(self, name: str) -> Database:
        return self.get_database(name=name)

    def set_write_concern(
        self,
        /,
        *,
        w: str | int,
        j: bool | None = None,
        wtimeout: int = 0,
    ) -> Self:
        """This sets a WriteConcern for all requests.

        Returns:
            The Kover client instance with the updated write concern.
        """
        self._write_concern = WriteConcern(
            w=w,
            j=j,
            wtimeout=wtimeout,
        )
        return self

    @classmethod
    async def from_uri(
        cls,
        uri: str,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> Kover:
        """Create an instance of Kover client by passing a uri.

        Parameters:
            uri : The uri itself.
            loop : Optional asyncio loop

        Returns:
            An instance of newly created Kover client.
        """
        parsed = await parse_uri(uri)
        pool = await ConnectionPool.from_parsed_uri(parsed, loop=loop)
        write_concern = WriteConcern(
            w=parsed.options.get("w", "majority"),
            j=parsed.options.get("journal"),
            wtimeout=parsed.options.get("wTimeoutMS", 0),
        )
        return cls(write_concern=write_concern, pool=pool)

    @classmethod
    async def make_client(
        cls,
        host: str = "127.0.0.1",
        port: int = DEFAULT_MONGODB_PORT,
        *,
        credentials: AuthCredentials | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        compression: CompressionT | None = None,
        tls: bool = False,
        application: DictT | None = None,
        w: str | int = "majority",
        max_pool_size: int = 100,
    ) -> Kover:
        """Create and return a new Kover client instance.

        Parameters:
            host : The hostname of the MongoDB server, by default "127.0.0.1".
            port : The port number of the MongoDB server, by default 27017.
            credentials : Authentication credentials, if required.
            loop : The event loop to use for asynchronous operations.
            compression : List of compression options.
            tls : the boolean value that indicated whether to use tls or no.
            application : document that will be included in hello payload
                under the "application" field.
            w : the value of default write concern used.
            max_pool_size : The maximum number of pooled connections.

        Returns:
            An instance of the Kover client.
        """
        pool = ConnectionPool(
            host,
            port,
            credentials=credentials,
            loop=loop,
            compression=list(compression) if compression is not None else None,
            tls=tls,
            application=application,
            max_pool_size=max_pool_size,
        )
        write_concern = WriteConcern(w=w)
        return cls(write_concern=write_concern, pool=pool)

    async def request(
        self,
        doc: DocumentT,
        *,
        db_name: str = "admin",
        session: Session | None = None,
        wait_response: bool = True,
        write_concern: WriteConcern | None = None,
        deadline: float | None = None,
    ) -> DictT:
        """Send a request to MongoDB Server.

        Returns:
            Document, containing response from the server.

        Raises:
            ValueError: if session belongs to different client.
        """
        doc = doc.copy()
        wc_allowed = next(iter(doc.keys()), None) in _WRITE_CONCERN_COMMANDS
        in_transaction = session is not None and session.in_transaction

        if write_concern is None:
            write_concern = self._write_concern

        if not in_transaction and wc_allowed and "writeConcern" not in doc:
            doc["writeConcern"] = maybe_to_dict(write_concern)

        if session is not None and session.client is not self:
            raise ValueError("Session belongs to a different client")

        return await self._pool.request(
            doc,
            db_name=db_name,
            session=session,
            wait_response=wait_response,
            deadline=deadline,
        )

    def bulk_write(
        self,
        document: DictT,
        session: Session | None = None,
    ) -> Cursor[DictT]:
        """Execute a bulkWrite operation and return info about it.

        Returns:
            Document, containing info about this operation.
        """
        database = self.get_database("admin")
        collection = database.get_collection("$cmd.bulkWrite")
        return Cursor(
            query=document,
            collection=collection,
            decoder=raw_decoder,
            session=session,
        )

    async def refresh_sessions(self, sessions: list[Session]) -> None:
        """Refresh the provided list of sessions.

        Parameters:
            sessions : A list of Session objects to be refreshed.

        Raises:
            ValueError: if session does not belong to ours.
        """
        for session in sessions:
            if session.client is not self:
                raise ValueError("Cannot refresh foreign session")

        documents: list[DictT] = [x.document for x in sessions]
        await self.request({"refreshSessions": documents})

    async def end_sessions(self, sessions: list[Session]) -> None:
        """End the provided list of sessions.

        Parameters:
            sessions : A list of Session objects to be ended.

        Raises:
            ValueError: if session does not belong to ours.
        """
        for session in sessions:
            if session.client is not self:
                raise ValueError("Cannot end foreign session")

        documents: list[DictT] = [x.document for x in sessions]
        await self.request({"endSessions": documents})

    async def start_session(self) -> Session:
        """Start a new session.

        Returns:
            An instance of the Session class representing the started session.
        """
        req = await self.request({"startSession": 1.0})
        return Session(document=req["id"], client=self)

    async def build_info(self) -> BuildInfo:
        """Retrieve build information from the MongoDB server.

        Returns:
            An instance of BuildInfo containing server build details.
        """
        request = await self.request({"buildInfo": 1.0})
        return BuildInfo.model_validate(request)

    async def logout(self) -> None:
        """Log out the current user session.

        This method sends a logout request to the server
        to terminate the current authenticated session.
        """
        await self.request({"logout": 1.0})

    async def list_database_names(self) -> list[str]:
        """Retrieve the names of all databases on the MongoDB server.

        Returns:
            A list containing the names of all databases.
        """
        command: DictT = {
            "listDatabases": 1.0,
            "nameOnly": True,
        }
        request = await self.request(command)
        return [x["name"] for x in request["databases"]]

    async def drop_database(self, name: str) -> None:
        """Drop the specified database from the MongoDB server.

        Parameters:
            name : The name of the database to drop.
        """
        await self.request({"dropDatabase": 1.0}, db_name=name)

    # https://www.mongodb.com/docs/manual/reference/command/dropConnections
    async def drop_connections(
        self,
        hosts: list[str],
        comment: str | None = None,
    ) -> None:
        """Drop connections to the specified hosts.

        Parameters:
            hosts : A list of hostnames whose connections should be dropped.
            comment : Optional comment for the operation.
        """
        document: DictT = filter_non_null({
            "dropConnections": 1.0,
            "hostAndPort": hosts,
            "comment": comment,
        })
        await self.request(document)

    # https://www.mongodb.com/docs/manual/reference/command/replSetInitiate/
    async def replica_set_initiate(
        self,
        config: ReplicaSetConfig | None = None,
    ) -> None:
        """Initiate a replica set with the provided configuration.

        Parameters:
            config : The configuration document for the replica set. If None,
                default configuration is used.
        """
        document = maybe_to_dict(config) or {}
        await self.request({"replSetInitiate": document})

    # https://www.mongodb.com/docs/manual/reference/command/replSetReconfig/
    async def replica_set_reconfig(
        self,
        config: ReplicaSetConfig,
        *,
        force: bool = False,
        max_time_ms: int | None = None,
    ) -> None:
        """Perform Reconfiguration of a replica set.

        Parameters:
            config : The configuration document for the replica set.
        """
        document: DictT = filter_non_null({
            "replSetReconfig": maybe_to_dict(config) or {},
            "force": force,
            "maxTimeMS": max_time_ms,
        })
        await self.request(document)

    # https://www.mongodb.com/docs/manual/reference/command/replSetGetStatus/
    async def get_replica_set_status(self) -> DictT:
        """Retrieve the status of the replica set.

        Returns:
            A JSON document containing the replica set status information.
        """
        return await self.request({"replSetGetStatus": 1.0})

    # https://www.mongodb.com/docs/manual/reference/command/shutdown/
    async def shutdown(
        self,
        *,
        force: bool = False,
        timeout: int | None = None,  # ruff: ignore[async-function-with-timeout]
        comment: str | None = None,
    ) -> None:
        """Shut down the MongoDB server.

        Parameters:
            force : Whether to force the shutdown, by default False.
            timeout : Timeout in seconds before shutdown, by default None.
            comment : Optional comment for the shutdown command.
        """
        command = filter_non_null({
            "shutdown": 1.0,
            "force": force,
            "timeoutSecs": timeout,
            "comment": comment,
        })
        await self.request(command, wait_response=False)

    # https://www.mongodb.com/docs/manual/reference/command/getCmdLineOpts/
    async def get_commandline(self) -> list[str]:
        """Retrieve the command line args used to start the MongoDB server.

        Returns:
            A list of command line arguments.
        """
        r = await self.request({"getCmdLineOpts": 1.0})
        return r["argv"]

    # https://www.mongodb.com/docs/manual/reference/command/getLog/#getlog
    async def get_log(
        self,
        parameter: Literal["global", "startupWarnings"] = "startupWarnings",
    ) -> list[DictT]:
        """Retrieve log entries from the MongoDB server.

        Parameters:
            parameter : The log type to retrieve,
                defaults to "startupWarnings".

        Returns:
            A list of log entries as JSON objects.
        """
        r = await self.request({"getLog": parameter})
        return [
            json.loads(info) for info in r["log"]
        ]

    # https://www.mongodb.com/docs/manual/reference/command/renameCollection/
    async def rename_collection(
        self,
        target: str,
        *,
        new_name: str,
        drop_target: bool = False,
        comment: str | None = None,
    ) -> None:
        """Rename a collection in the MongoDB server.

        Parameters:
            target : The full name of the source collection to rename.
            new_name : The new name for the collection.
            drop_target : Whether to drop the target collection if it exists,
                by default False.
            comment : Optional comment for the rename operation.
        """
        command = filter_non_null({
            "renameCollection": target,
            "to": new_name,
            "dropTarget": drop_target,
            "comment": comment,
        })
        await self.request(command)

    # https://www.mongodb.com/docs/manual/reference/command/setUserWriteBlockMode/
    async def set_user_write_block_mode(self, *, param: bool) -> None:
        """Set the user write block mode on the MongoDB server.

        Parameters:
            param : Blocks writes on a cluster when set to true.
                To enable writes on a cluster, set global: false.
        """
        await self.request({
            "setUserWriteBlockMode": 1.0,
            "global": param,
        })

    # https://www.mongodb.com/docs/manual/reference/command/fsync/
    async def fsync(
        self,
        *,
        timeout: int = 90000,  # ruff: ignore[async-function-with-timeout]
        lock: bool = True,
        comment: str | None = None,
    ) -> None:
        """Flush all pending writes to disk and optionally lock the database.

        Parameters:
            timeout : Timeout in milliseconds for acquiring the
                fsync lock, by default 90000.
            lock : Whether to lock the database after flushing,
                by default True.
            comment : Optional comment for the fsync operation.
        """
        command = filter_non_null({
            "fsync": 1.0,
            "fsyncLockAcquisitionTimeoutMillis": timeout,
            "lock": lock,
            "comment": comment,
        })
        await self.request(command)

    # https://www.mongodb.com/docs/manual/reference/command/fsyncUnlock/
    async def fsync_unlock(self, comment: str | None = None) -> None:
        """Unlock the database after a previous fsync lock operation.

        Parameters:
            comment : Optional comment for the fsync unlock operation.
        """
        command = filter_non_null({
            "fsyncUnlock": 1.0,
            "comment": comment,
        })
        await self.request(command)

    # https://www.mongodb.com/docs/manual/reference/command/getDefaultRWConcern
    async def get_default_rw_concern(
        self,
        *,
        in_memory: bool = False,
        comment: str | None = None,
    ) -> tuple[ReadConcern, WriteConcern]:
        """Get the default read and write concern settings for the database.

        Parameters:
            in_memory : Set to true to return the in-memory cached copy
                of the global default read or write concern settings.
                The instance uses the in-memory copy when applying
                the global defaults to an operation.
                Set to false to return the on-disk copy of the deployment's
                global default read or write concern. Defaults to false.
            comment : Optional comment for the operation.

        Returns:
            An instance of WriteConcern representing the default settings.
        """
        command = filter_non_null({
            "getDefaultRWConcern": 1.0,
            "inMemory": in_memory,
            "comment": comment,
        })
        resp = await self.request(command)
        read_concern = ReadConcern(level=resp["defaultReadConcern"]["level"])
        write_concern = WriteConcern(w=resp["defaultWriteConcern"]["w"])

        return read_concern, write_concern

    # https://www.mongodb.com/docs/manual/reference/command/getParameter
    async def get_parameter(self, name: str) -> object:
        """Get the value of a specific server parameter.

        Parameters:
            name : The name of the server parameter to retrieve.

        Returns:
            A Parameter itself.
        """
        resp = await self.request({"getParameter": 1.0, name: 1.0})
        return resp[name]

    # https://www.mongodb.com/docs/manual/reference/command/setParameter
    async def set_parameter(self, name: str, value: object) -> None:
        """Set the server parameter at runtime.

        Parameters:
            name : The name of the server parameter to set.
            value : The value of that parameter.
        """
        await self.request({"setParameter": 1.0, name: value})
