from __future__ import annotations

from typing import TYPE_CHECKING

from .collection import Collection
from .models import User
from .utils import filter_non_null

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .client import Kover
    from .session import Transaction
    from .typings import xJsonT


class Database:
    """Represents a database instance, providing methods to manage collections and users.

    Attributes:
    ----------
    name : str
        The name of the database.
    client : Kover
        The client instance used to communicate with the database.

    Methods:
    -------
    get_collection(name: str) -> Collection
        Returns a collection object by name.
    list_collections(...)
        Lists collections in the database.
    create_collection(...)
        Creates a new collection.
    drop_collection(name: str)
        Drops a collection by name.
    create_user(...)
        Creates a new user in the database.
    users_info(...)
        Retrieves information about users.
    drop_user(name: str)
        Drops a user from the database.
    grant_roles_to_user(username: str, roles: list)
        Grants roles to a user.
    command(doc: xJsonT, ...)
        Sends a command to the database.
    ping() -> bool
        Checks if the database is reachable.
    """  # noqa: E501

    def __init__(self, name: str, client: Kover) -> None:
        self.name = name
        self.client = client

    def get_collection(self, name: str) -> Collection:
        """Returns a collection object by name.

        Parameters
        ----------
        name : str
            The name of the collection to retrieve.

        Returns:
        -------
        Collection
            The collection object corresponding to the given name.
        """
        return Collection(name=name, database=self)

    def __getattr__(self, name: str) -> Collection:
        return self.get_collection(name=name)

    async def list_collections(
        self,
        filter_: xJsonT | None = None,
        name_only: bool = False,
        authorized_collections: bool = False,
        comment: str | None = None,
    ) -> list[Collection]:
        """Lists collections in the database.

        Parameters
        ----------
        filter_ : xJsonT | None, optional
            A filter to apply to the collections.
        name_only : bool, optional
            If True, only collection names are returned.
        authorized_collections : bool, optional
            If True, only authorized collections are listed.
        comment : str | None, optional
            Optional comment for the operation.

        Returns:
        -------
        list[Collection]
            A list of Collection objects or collection names if name_only is True.
        """  # noqa: E501
        request = await self.command({
            "listCollections": 1.0,
            "filter": filter_ or {},
            "nameOnly": name_only,
            "authorizedCollections": authorized_collections,
            "comment": comment,
        })
        return [Collection(
            name=x["name"],
            database=self,
            options=x["options"],
            info=x["info"],
        ) if not name_only else x["name"]
            for x in request["cursor"]["firstBatch"]
        ]

    async def create_collection(
        self,
        name: str,
        params: xJsonT | None = None,
    ) -> Collection:
        """Creates a new collection in the database.

        Parameters
        ----------
        name : str
            The name of the collection to create.
        params : xJsonT | None, optional
            Additional parameters for collection creation.

        Returns:
        -------
        Collection
            The created collection object.
        """
        await self.command({
            "create": name, **(params or {}),
        })
        return self.get_collection(name)

    async def drop_collection(self, name: str) -> None:
        """Drops a collection by name.

        Parameters
        ----------
        name : str
            The name of the collection to drop.

        Returns:
        -------
        None
        """
        # TODO @megawattka: add `comment` parameter
        # TODO @megawattka: add return type bool depending on success
        await self.command({"drop": name})

    # https://gist.github.com/xandout/61d25df23a77236ab28236650f84ce6b
    async def create_user(
        self,
        name: str,
        password: str,
        roles: Sequence[xJsonT | str] | None = None,
        custom_data: xJsonT | None = None,
        mechanisms: list[str] | None = None,
        comment: str | None = None,
        root: bool = False,
    ) -> None:
        """Creates a new user in the database.

        Parameters
        ----------
        name : str
            The name of the user to create.
        password : str
            The password for the user.
        roles : Sequence[xJsonT | str] | None, optional
            Roles to assign to the user.
        custom_data : xJsonT | None, optional
            Custom data to associate with the user.
        mechanisms : list[str] | None, optional
            Authentication mechanisms for the user.
        comment : str | None, optional
            Optional comment for the operation.
        root : bool, optional
            If True, assigns root roles to the user.

        Returns:
        -------
        None

        Raises:
        ------
        ValueError
            If user roles are not specified.
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
        query: str | xJsonT | list[xJsonT] | None = None,
        show_credentials: bool = False,
        show_custom_data: bool = False,
        show_privileges: bool = False,
        show_auth_restrictions: bool = False,
        filter_: xJsonT | None = None,
        comment: str | None = None,
    ) -> list[User]:
        """Retrieves information about users in the database.

        Parameters
        ----------
        query : str | xJsonT | list[xJsonT] | None, optional
            Query to filter users; can be a username,
            a query document, or a list of query documents.
        show_credentials : bool, optional
            Whether to include user credentials in the result.
        show_custom_data : bool, optional
            Whether to include custom data associated with users.
        show_privileges : bool, optional
            Whether to include user privileges in the result.
        show_auth_restrictions : bool, optional
            Whether to include authentication restrictions.
        filter_ : xJsonT | None, optional
            Additional filter for users.
        comment : str | None, optional
            Optional comment for the operation.

        Returns:
        -------
        list[User]
            A list of User objects matching the query.
        """
        if query is None:
            query = 1.0  # type: ignore
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

        Parameters
        ----------
        name : str
            The name of the user to drop.
        comment : str | None, optional
            Optional comment for the operation.

        Returns:
        -------
        None
        """
        command = filter_non_null({
            "dropUser": name,
            "comment": comment,
        })
        await self.command(command)

    async def grant_roles_to_user(
        self,
        username: str,
        roles: list[str | xJsonT],
    ) -> None:
        """Grants roles to a user in the database.

        Parameters
        ----------
        username : str
            The name of the user to grant roles to.
        roles : list[str | xJsonT]
            A list of roles or role documents to assign to the user.

        Returns:
        -------
        None
        """
        await self.command({
            "grantRolesToUser": username,
            "roles": roles,
        })

    async def command(
        self,
        doc: xJsonT,
        /,
        *,
        transaction: Transaction | None = None,
    ) -> xJsonT:
        """Sends a command to the database.

        Parameters
        ----------
        doc : xJsonT
            The command document to send.
        transaction : Transaction | None, optional
            An optional transaction context.

        Returns:
        -------
        xJsonT
            The response from the database.
        """
        return await self.client.socket.request(
            doc=doc,
            transaction=transaction,
            db_name=self.name,
        )

    # https://www.mongodb.com/docs/manual/reference/command/ping/
    async def ping(self) -> bool:
        """Checks if the database is reachable by sending a ping command.

        Returns:
        -------
        bool
            True if the database responds successfully, False otherwise.
        """
        r = await self.command({"ping": 1.0})
        return r["ok"] == 1.0
