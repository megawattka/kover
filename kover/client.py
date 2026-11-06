"""High-level MongoDB API backed by an injected command executor."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal, Self

from ._utils import (
    classrepr,
    filter_non_null,
    maybe_to_dict,
    raw_decoder,
)
from .cursor import Cursor
from .models import BuildInfo, ReadConcern, WriteConcern
from .session import Session

if TYPE_CHECKING:
    from .database import Database
    from .execution.protocols import ICommandExecutor
    from .models.address import Address
    from .models.read_preference import ReadPreference
    from .models.replica_set import ReplicaSetConfig


@classrepr("_write_concern", "_executor")
class Kover:
    """Expose database and administrative helpers through an executor.

    Connection setup and resource composition belong to the caller. Routing,
    command preparation, sessions metadata, and I/O belong to the executor.
    Closing the client closes its injected executor.
    """

    def __init__(
        self,
        executor: ICommandExecutor,
        *,
        write_concern: WriteConcern | None = None,
    ) -> None:
        self._write_concern = write_concern or WriteConcern()
        self._executor = executor

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        await self.close()
        return False

    async def close(self) -> None:
        """Release the resources owned by the client."""
        await self._executor.close()

    def get_database(self, name: str) -> Database:
        """Get a Database instance for the specified database name.

        Parameters:
            name : The name of the database to retrieve.

        Returns:
            An instance of the Database class for the given name.
        """
        from .database import Database  # ruff: ignore[import-outside-top-level]

        return Database(name=name, client=self)

    def __getattr__(self, name: str) -> Database:
        if name.startswith("_"):
            raise AttributeError(name)

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

    async def command(
        self,
        doc: dict[str, Any],
        *,
        db_name: str = "admin",
        session: Session | None = None,
        write_concern: WriteConcern | None = None,
        deadline: float | None = None,
        read_preference: ReadPreference | None = None,
        server_address: Address | None = None,
    ) -> dict[str, Any]:
        """Send a request to MongoDB Server.

        Read preference overrides apply only to eligible reads; writes and
        unknown commands use primary routing. Transactions require primary
        reads. server_address is reserved for getMore/killCursors affinity.

        Returns:
            Document, containing response from the server.

        Raises:
            ValueError: If the session belongs to another client or a
                transaction read requests a non-primary preference.
        """
        if session is not None and session.client is not self:
            raise ValueError("Session belongs to a different client")

        return await self._executor.execute(
            doc,
            database=db_name,
            session=session,
            deadline=deadline,
            read_preference=read_preference,
            server_address=server_address,
            write_concern=(
                write_concern if write_concern is not None
                else self._write_concern
            ),
        )

    def bulk_write(
        self,
        document: dict[str, Any],
        session: Session | None = None,
    ) -> Cursor[dict[str, Any]]:
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

        documents: list[dict[str, Any]] = [x.document for x in sessions]
        await self.command({"refreshSessions": documents})

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

        documents: list[dict[str, Any]] = [x.document for x in sessions]
        await self.command({"endSessions": documents})

    async def start_session(self) -> Session:
        """Start a new session.

        Returns:
            An instance of the Session class representing the started session.
        """
        req = await self.command({"startSession": 1.0})
        return Session(document=req["id"], client=self)

    async def build_info(self) -> BuildInfo:
        """Retrieve build information from the MongoDB server.

        Returns:
            An instance of BuildInfo containing server build details.
        """
        request = await self.command({"buildInfo": 1.0})
        return BuildInfo.model_validate(request)

    async def logout(self) -> None:
        """Log out the current user session.

        This method sends a logout request to the server
        to terminate the current authenticated session.
        """
        await self.command({"logout": 1.0})

    async def list_database_names(self) -> list[str]:
        """Retrieve the names of all databases on the MongoDB server.

        Returns:
            A list containing the names of all databases.
        """
        command: dict[str, Any] = {
            "listDatabases": 1.0,
            "nameOnly": True,
        }
        request = await self.command(command)
        return [x["name"] for x in request["databases"]]

    async def drop_database(self, name: str) -> None:
        """Drop the specified database from the MongoDB server.

        Parameters:
            name : The name of the database to drop.
        """
        await self.command({"dropDatabase": 1.0}, db_name=name)

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
        document: dict[str, Any] = filter_non_null({
            "dropConnections": 1.0,
            "hostAndPort": hosts,
            "comment": comment,
        })
        await self.command(document)

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
        await self.command({"replSetInitiate": document})

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
        document: dict[str, Any] = filter_non_null({
            "replSetReconfig": maybe_to_dict(config) or {},
            "force": force,
            "maxTimeMS": max_time_ms,
        })
        await self.command(document)

    # https://www.mongodb.com/docs/manual/reference/command/replSetGetStatus/
    async def get_replica_set_status(self) -> dict[str, Any]:
        """Retrieve the status of the replica set.

        Returns:
            A JSON document containing the replica set status information.
        """
        return await self.command({"replSetGetStatus": 1.0})

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
        await self.command(command)

    # https://www.mongodb.com/docs/manual/reference/command/getCmdLineOpts/
    async def get_commandline(self) -> list[str]:
        """Retrieve the command line args used to start the MongoDB server.

        Returns:
            A list of command line arguments.
        """
        r = await self.command({"getCmdLineOpts": 1.0})
        return r["argv"]

    # https://www.mongodb.com/docs/manual/reference/command/getLog/#getlog
    async def get_log(
        self,
        parameter: Literal["global", "startupWarnings"] = "startupWarnings",
    ) -> list[dict[str, Any]]:
        """Retrieve log entries from the MongoDB server.

        Parameters:
            parameter : The log type to retrieve,
                defaults to "startupWarnings".

        Returns:
            A list of log entries as JSON objects.
        """
        r = await self.command({"getLog": parameter})
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
        await self.command(command)

    # https://www.mongodb.com/docs/manual/reference/command/setUserWriteBlockMode/
    async def set_user_write_block_mode(self, *, param: bool) -> None:
        """Set the user write block mode on the MongoDB server.

        Parameters:
            param : Blocks writes on a cluster when set to true.
                To enable writes on a cluster, set global: false.
        """
        await self.command({
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
        await self.command(command)

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
        await self.command(command)

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
        resp = await self.command(command)
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
        resp = await self.command({"getParameter": 1.0, name: 1.0})
        return resp[name]

    # https://www.mongodb.com/docs/manual/reference/command/setParameter
    async def set_parameter(self, name: str, value: object) -> None:
        """Set the server parameter at runtime.

        Parameters:
            name : The name of the server parameter to set.
            value : The value of that parameter.
        """
        await self.command({"setParameter": 1.0, name: value})
