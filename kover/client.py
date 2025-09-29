"""Kover Client Module."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Literal

from typing_extensions import Self

from .database import Database
from .helpers import (
    classrepr,
    filter_non_null,
    maybe_to_dict,
)
from .models import BuildInfo, ReadConcern, WriteConcern
from .network import MongoTransport, SrvResolver
from .schema import SchemaGenerator
from .session import Session
from .typings import DEFAULT_MONGODB_PORT
from .uri_parser import parse_uri

if TYPE_CHECKING:
    from .models import ReplicaSetConfig
    from .network import AuthCredentials
    from .schema import Document
    from .transaction import Transaction
    from .typings import COMPRESSION_T, DocumentT, xJsonT


def _create_connection_pool(
    host: str,
    port: int,
    size: int,
    *,
    tls: bool,
    loop: asyncio.AbstractEventLoop | None = None,
) -> asyncio.Queue[MongoTransport]:
    """Gives us a filled connection pool.

    Returns:
        Pool, filled with non connected connections.
    """
    pool: asyncio.Queue[MongoTransport] = asyncio.Queue()
    for _ in range(size):
        pool.put_nowait(MongoTransport(host, port, loop=loop, tls=tls))
    return pool


@classrepr("_write_concern", "_compression", "_application")
class Kover:
    """Kover client for interacting with a MongoDB server."""

    def __init__(
        self,
        *,
        w: str | int = "majority",
        pool: asyncio.Queue[MongoTransport],
        credentials: AuthCredentials | None = None,
        compression: COMPRESSION_T | None = None,
        application: xJsonT | None = None,
    ) -> None:
        self._write_concern = WriteConcern(w=w)
        self._pool = pool
        self._credentials = credentials
        self._compression = compression
        self._application = application
        self._schema_generator = SchemaGenerator()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        await self.close()
        return True

    async def close(self) -> None:
        """Close the underlying transport connections.

        This method closes the transport writer
        and waits until the connection is fully closed.
        """
        if self._pool.empty():
            return

        while not self._pool.empty():
            conn = await self._pool.get()
            await conn.close()

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
        self._write_concern = WriteConcern(w=w, j=j, wtimeout=wtimeout)
        return self

    def generate_schema(self, cls: type[Document]) -> xJsonT:
        """Generate a JSON schema for the provided Document class.

        Parameters:
            cls : The Document class for which to generate the schema.

        Returns:
            A JSON schema as a dictionary.
        """
        return self._schema_generator.generate(cls)

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
        parsed = parse_uri(uri)

        if parsed.scheme == "mongodb+srv":
            resolver = SrvResolver()
            nodes = await resolver.get_nodes(parsed.hostname)
            assert nodes, "Node resolution failed."
        else:
            nodes = [parsed.hostname]

        transport = MongoTransport(
            nodes[0], parsed.port, loop=loop, tls=parsed.tls)

        await transport.connect()
        hello = await transport.hello(
            parsed.compressors, parsed.credentials, parsed.application)
        await transport.close()

        if not hello.is_primary:
            assert hello.primary_node, "Primary node resolution failed."

            host, _ = hello.primary_node.split(":")
            nodes = [host]

        args = (nodes[0], parsed.port, parsed.max_pool_size)
        pool = _create_connection_pool(*args, tls=parsed.tls, loop=loop)

        return cls(
            w=parsed.write_concern,
            pool=pool,
            credentials=parsed.credentials,
            compression=parsed.compressors,
            application=parsed.application,
        )

    @classmethod
    async def make_client(
        cls,
        host: str = "127.0.0.1",
        port: int = DEFAULT_MONGODB_PORT,
        *,
        credentials: AuthCredentials | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        compression: COMPRESSION_T | None = None,
        tls: bool = False,
        application: xJsonT | None = None,
        write_concern: str | int = "majority",
        max_pool_size: int = 100,
    ) -> Kover:
        """Create and return a new Kover client instance.

        Parameters:
            host : The hostname of the MongoDB server, by default "127.0.0.1".
            port : The port number of the MongoDB server, by default 27017.
            credentials : Authentication credentials, if required.
            loop : The event loop to use for asynchronous operations.
            compression : List of compression options.
            default_database : the name of a database that will be returned
                by Kover.get_default_database().
            tls : the boolean value that indicated whether to use tls or no.
            application : document that will be included in hello payload
                under the "application" field.
            write_concern : the value of default write concern used.

        Returns:
            An instance of the Kover client.
        """
        pool = _create_connection_pool(
            host, port, max_pool_size, tls=tls, loop=loop)

        return cls(
            w=write_concern,
            pool=pool,
            credentials=credentials,
            compression=compression,
            application=application,
        )

    async def request(
        self,
        doc: DocumentT,
        *,
        db_name: str = "admin",
        transaction: Transaction | None = None,
        wait_response: bool = True,
    ) -> xJsonT:
        """Send a request to MongoDB Server.

        Returns:
            Document, containing response from the server.
        """
        conn = await self._pool.get()
        if not conn.is_connected:
            await conn.connect()
            hello = await conn.hello(
                self._compression, self._credentials, self._application)

            if hello.requires_auth:
                mechanism = hello.get_auth_mechanism()
                await conn.authorize(mechanism, credentials=self._credentials)
        try:
            return await conn.request(
                doc,
                db_name=db_name,
                transaction=transaction,
                wait_response=wait_response,
            )
        finally:
            await self._pool.put(conn)

    async def bulk_write(
        self,
        document: xJsonT,
        transaction: Transaction | None = None,
    ) -> xJsonT:
        """Execute a bulkWrite operation and return info about it.

        Returns:
            Document, containing info about this operation.
        """
        return await self.request(document, transaction=transaction)

    async def refresh_sessions(self, sessions: list[Session]) -> None:
        """Refresh the provided list of sessions.

        Parameters:
            sessions : A list of Session objects to be refreshed.
        """
        documents: list[xJsonT] = [x.document for x in sessions]
        await self.request({"refreshSessions": documents})

    async def end_sessions(self, sessions: list[Session]) -> None:
        """End the provided list of sessions.

        Parameters:
            sessions : A list of Session objects to be ended.
        """
        documents: list[xJsonT] = [x.document for x in sessions]
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
        command: xJsonT = {
            "listDatabases": 1.0,
            "nameOnly": True  # noqa: COM812
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
        document: xJsonT = filter_non_null({
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
        document: xJsonT = filter_non_null({
            "replSetReconfig": maybe_to_dict(config) or {},
            "force": force,
            "maxTimeMS": max_time_ms,
        })
        await self.request(document)

    # https://www.mongodb.com/docs/manual/reference/command/replSetGetStatus/
    async def get_replica_set_status(self) -> xJsonT:
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
        timeout: int | None = None,
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
    ) -> list[xJsonT]:
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
        timeout: int = 90000,
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
            in_memory : If True, returns a WriteConcern instance without
                querying the server, by default False.
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
