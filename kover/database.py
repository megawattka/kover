"""Kover Database Module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .collection import Collection
from .cursor import Cursor
from .helpers import classrepr, filter_non_null, maybe_to_dict, raw_decoder
from .models import User

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .client import Kover
    from .models import WriteConcern
    from .models.network import Address
    from .read_preferences import ReadPreference
    from .session import Session
    from .typings import DictT


@classrepr("name", "client")
class Database:
    """Represents a database instance, providing methods to manage database.

    Attributes:
        name : The name of the database.
        client : The client instance used to communicate with the database.
    """

    def __init__(self, name: str, client: Kover) -> None:
        self.name = name
        self.client = client

    def get_collection(self, name: str) -> Collection:
        """Returns a collection object by name.

        Parameters:
            name : The name of the collection to retrieve.

        Returns:
            The collection object corresponding to the given name.
        """
        return Collection(name=name, database=self)

    def __getattr__(self, name: str) -> Collection:
        return self.get_collection(name=name)

    async def list_collections(
        self,
        filter_: DictT | None = None,
        *,
        name_only: bool = False,
        authorized_collections: bool = False,
        comment: str | None = None,
    ) -> list[Collection]:
        """Lists collections in the database.

        Parameters:
            filter_ : A filter to apply to the collections.
            name_only : If True, only collection names are returned.
            authorized_collections : If True, only authorized
                collections are listed.
            comment : Optional comment for the operation.

        Returns:
            A list of Collection objects or collection names
                if name_only is True.
        """
        command = filter_non_null({
            "listCollections": 1.0,
            "filter": filter_ or {},
            "nameOnly": name_only,
            "authorizedCollections": authorized_collections,
            "comment": comment,
        })
        cursor: Cursor[DictT] = Cursor(
            command,
            self.get_collection("$cmd.listCollections"),
            decoder=raw_decoder,
        )
        if name_only:
            return [entry["name"] async for entry in cursor]

        return [
            Collection(
                name=entry["name"],
                database=self,
                options=entry.get("options"),
                info=entry.get("info"),
            )
            async for entry in cursor
        ]

    async def create_collection(
        self,
        name: str,
        params: DictT | None = None,
    ) -> Collection:
        """Creates a new collection in the database.

        Parameters:
            name : The name of the collection to create.
            params : Additional parameters for collection creation.

        Returns:
            The created collection object.
        """
        await self.command({
            "create": name, **(params or {}),
        })
        return self.get_collection(name)

    async def drop_collection(
        self,
        name: str,
        comment: str | None = None,
    ) -> None:
        """Drops a collection by name.

        Parameters
            name : The name of the collection to drop.
            comment : Optional comment for the operation.
        """
        command = filter_non_null({"drop": name, "comment": comment})
        await self.command(command)

    # https://gist.github.com/xandout/61d25df23a77236ab28236650f84ce6b
    async def create_user(
        self,
        name: str,
        password: str,
        *,
        roles: Sequence[DictT | str] | None = None,
        custom_data: DictT | None = None,
        mechanisms: list[str] | None = None,
        comment: str | None = None,
        root: bool = False,
    ) -> None:
        """Creates a new user in the database.

        Parameters
            name : The name of the user to create.
            password : The password for the user.
            roles : Roles to assign to the user.
            custom_data : Custom data to associate with the user.
            mechanisms : Authentication mechanisms for the user.
            comment : Optional comment for the operation.
            root : If True, assigns root roles to the user.

        Raises:
            ValueError : If user roles are not specified.
        """
        if mechanisms is None:
            mechanisms = ["SCRAM-SHA-1", "SCRAM-SHA-256"]

        if root is True and roles is None:
            roles = [
                {"role": "userAdminAnyDatabase", "db": "admin"},
                {"role": "root", "db": "admin"},
                {"role": "readWriteAnyDatabase", "db": "admin"},
            ]
        if roles is None:
            raise ValueError("You need to specify user roles.")

        command = filter_non_null({
            "createUser": name,
            "pwd": password,
            "mechanisms": mechanisms,
            "roles": roles,
            "customData": custom_data,
            "comment": comment,
        })
        await self.command(command)

    async def users_info(
        self,
        query: str | DictT | list[DictT] | float | None = None,
        *,
        show_credentials: bool = False,
        show_custom_data: bool = False,
        show_privileges: bool = False,
        show_auth_restrictions: bool = False,
        filter_: DictT | None = None,
        comment: str | None = None,
    ) -> list[User]:
        """Retrieves information about users in the database.

        Parameters:
            query : Query to filter users; can be a username,
                a query document, or a list of query documents.
            show_credentials : Whether to include user
                credentials in the result.
            show_custom_data : Whether to include custom data associated
                with users.
            show_privileges : Whether to include user privileges in the result.
            show_auth_restrictions : Whether to include authentication
                restrictions.
            filter_ : Additional filter.
            comment : Optional comment for the operation.

        Returns:
            A list of User objects matching the query.
        """
        if query is None:
            query = 1.0

        command = filter_non_null({
            "usersInfo": query,
            "showCredentials": show_credentials,
            "showCustomData": show_custom_data,
            "showPrivileges": show_privileges,
            "showAuthenticationRestrictions": show_auth_restrictions,
            "filter": filter_,
            "comment": comment,
        })
        request = await self.command(command)
        return [User(**x) for x in request["users"]]

    async def drop_user(
        self,
        name: str,
        comment: str | None = None,
    ) -> None:
        """Drops a user from the database.

        Parameters:
            name : The name of the user to drop.
            comment : Optional comment for the operation.
        """
        command = filter_non_null({
            "dropUser": name,
            "comment": comment,
        })
        await self.command(command)

    async def drop_all_users_from_database(
        self,
        write_concern: WriteConcern | None = None,
        comment: str | None = None,
    ) -> int:
        """Drops all users from the database.

        Parameters:
            write_concern : Optional write concern for the operation.
            comment : Optional comment for the operation.

        Returns:
            The number of users dropped.
        """
        command = filter_non_null({
            "dropAllUsersFromDatabase": 1.0,
            "writeConcern": maybe_to_dict(write_concern),
            "comment": comment,
        })
        resp = await self.command(command)
        return resp["n"]

    async def grant_roles_to_user(
        self,
        username: str,
        roles: list[str | DictT],
    ) -> None:
        """Grants roles to a user in the database.

        Parameters:
            username : The name of the user to grant roles to.
            roles : A list of roles or role documents to assign to the user.
        """
        await self.command({
            "grantRolesToUser": username,
            "roles": roles,
        })

    async def command(
        self,
        doc: DictT,
        /,
        *,
        session: Session | None = None,
        write_concern: WriteConcern | None = None,
        read_preference: ReadPreference | None = None,
        server_address: Address | None = None,
    ) -> DictT:
        """Sends a command to the database.

        Parameters:
            doc : The command document to send.
            session : An optional logical session.
            write_concern : Optional write concern override for the operation.
            read_preference : Optional read routing override.
            server_address : Source address for cursor continuation commands.

        Returns:
            The response from the database.

        Raises:
            ValueError: if clients are different
        """
        if session is not None and session.client is not self.client:
            raise ValueError("Session belongs to a different client")

        routing: DictT = {}
        if read_preference is not None:
            routing["read_preference"] = read_preference
        if server_address is not None:
            routing["server_address"] = server_address
        return await self.client.request(
            doc=doc,
            session=session,
            db_name=self.name,
            write_concern=write_concern,
            **routing,
        )

    # https://www.mongodb.com/docs/manual/reference/command/ping/
    async def ping(self) -> bool:
        """Checks if the database is reachable by sending a ping command.

        Returns:
            True if the database responds successfully.
        """
        r = await self.command({"ping": 1.0})
        return r["ok"] == 1
