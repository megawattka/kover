from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

from typing_extensions import Self

from .database import Database
from .helpers import classrepr, filter_non_null, maybe_to_dict
from .models import BuildInfo, WriteConcern
from .network import MongoTransport, SrvResolver
from .session import Session
from .uri_parser import parse_uri

if TYPE_CHECKING:
    import asyncio

    from .models import ReplicaSetConfig
    from .network import AuthCredentials
    from .typings import COMPRESSION_T, xJsonT


@classrepr("signature", "transport", "is_primary")
class Kover:
    """Kover client for interacting with a MongoDB server.

    Attributes:
        transport : The underlying transport to the MongoDB server.
        signature : The authentication signature, if authenticated.
        default_database : The name of the default database.
        is_primary : The flag that tells us whether that
            this is primary or secondary instance
    """

    def __init__(
        self,
        transport: MongoTransport,
        signature: bytes | None,
        *,
        is_primary: bool = False,
        w: str | int = "majority",
    ) -> None:
        self.transport = transport
        self.signature = signature
        self._is_primary = is_primary
        self._write_concern = WriteConcern(w=w)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        if self.signature is not None:
            await self.logout()
        await self.close()
        return True

    @property
    def is_primary(self) -> bool:
        """Whether this instance is a primary or not."""
        return self._is_primary

    async def close(self) -> None:
        """Close the underlying transport connection.

        This method closes the transport writer
        and waits until the connection is fully closed.
        """
        self.transport.writer.close()
        await self.transport.writer.wait_closed()

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
        """This sets a WriteConcern for all requests."""
        self._write_concern = WriteConcern(w=w, j=j, wtimeout=wtimeout)
        return self

    @classmethod
    async def from_uri(
        cls,
        uri: str,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> Kover:
        """Create an instance of Kover client by passing a uri."""
        parsed = parse_uri(uri)

        resolver = SrvResolver()
        nodes = await resolver.get_nodes(parsed.hostname)
        assert nodes, "Node resolution failed."

        transport = await MongoTransport.make(
            nodes[0], port=parsed.port, tls=parsed.tls, loop=loop)

        hello = await transport.hello(
            parsed.compressors, parsed.credentials, parsed.application)

        if not hello.is_primary:
            assert hello.primary_node, "Primary node resolution failed."

            host, _ = hello.primary_node.split(":")
            return await cls.make_client(
                host=host,
                port=parsed.port,
                credentials=parsed.credentials,
                loop=loop,
                compression=parsed.compressors,
                tls=parsed.tls,
                application=parsed.application,
                write_concern=parsed.write_concern,
            )

        mechanism = hello.get_auth_mechanism()
        signature = await transport.authorize(mechanism, parsed.credentials)

        return cls(
            transport=transport,
            signature=signature,
            is_primary=hello.is_primary,
            w=parsed.write_concern,
        )

    @classmethod
    async def make_client(
        cls,
        host: str = "127.0.0.1",
        port: int = 27017,
        *,
        credentials: AuthCredentials | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        compression: COMPRESSION_T | None = None,
        tls: bool = False,
        application: xJsonT | None = None,
        write_concern: str | int = "majority",
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
        transport = await MongoTransport.make(
            host=host, port=port, loop=loop, tls=tls)

        hello = await transport.hello(
            credentials=credentials,
            compression=compression,
            application=application,
        )
        mechanism = hello.get_auth_mechanism()
        signature = await transport.authorize(mechanism, credentials)

        return cls(
            transport,
            signature,
            is_primary=hello.is_primary,
            w=write_concern,
        )

    async def refresh_sessions(self, sessions: list[Session]) -> None:
        """Refresh the provided list of sessions.

        Parameters:
            sessions : A list of Session objects to be refreshed.
        """
        documents: list[xJsonT] = [x.document for x in sessions]
        await self.transport.request({"refreshSessions": documents})

    async def end_sessions(self, sessions: list[Session]) -> None:
        """End the provided list of sessions.

        Parameters:
            sessions : A list of Session objects to be ended.
        """
        documents: list[xJsonT] = [x.document for x in sessions]
        await self.transport.request({"endSessions": documents})

    async def start_session(self) -> Session:
        """Start a new session.

        Returns:
            An instance of the Session class representing the started session.
        """
        req = await self.transport.request({"startSession": 1.0})
        return Session(document=req["id"], transport=self.transport)

    async def build_info(self) -> BuildInfo:
        """Retrieve build information from the MongoDB server.

        Returns:
            An instance of BuildInfo containing server build details.
        """
        request = await self.transport.request({"buildInfo": 1.0})
        return BuildInfo.model_validate(request)

    async def logout(self) -> None:
        """Log out the current user session.

        This method sends a logout request to the server
        to terminate the current authenticated session.
        """
        await self.transport.request({"logout": 1.0})

    async def list_database_names(self) -> list[str]:
        """Retrieve the names of all databases on the MongoDB server.

        Returns:
            A list containing the names of all databases.
        """
        command: xJsonT = {
            "listDatabases": 1.0,
            "nameOnly": True  # noqa: COM812
        }
        request = await self.transport.request(command)
        return [x["name"] for x in request["databases"]]

    async def drop_database(self, name: str) -> None:
        """Drop the specified database from the MongoDB server.

        Parameters:
            name : The name of the database to drop.
        """
        await self.transport.request({"dropDatabase": 1.0}, db_name=name)

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
        await self.transport.request({"replSetInitiate": document})

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
        await self.transport.request(document)

    # https://www.mongodb.com/docs/manual/reference/command/replSetGetStatus/
    async def get_replica_set_status(self) -> xJsonT:
        """Retrieve the status of the replica set.

        Returns:
            A JSON document containing the replica set status information.
        """
        return await self.transport.request({"replSetGetStatus": 1.0})

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
        await self.transport.request(command, wait_response=False)

    # https://www.mongodb.com/docs/manual/reference/command/getCmdLineOpts/
    async def get_commandline(self) -> list[str]:
        """Retrieve the command line args used to start the MongoDB server.

        Returns:
            A list of command line arguments.
        """
        r = await self.transport.request({"getCmdLineOpts": 1.0})
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
        r = await self.transport.request({"getLog": parameter})
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
        await self.transport.request(command)

    # https://www.mongodb.com/docs/manual/reference/command/setUserWriteBlockMode/
    async def set_user_write_block_mode(self, *, param: bool) -> None:
        """Set the user write block mode on the MongoDB server.

        Parameters:
            param : Blocks writes on a cluster when set to true.
                To enable writes on a cluster, set global: false.
        """
        await self.transport.request({
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
        await self.transport.request(command)

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
        await self.transport.request(command)
