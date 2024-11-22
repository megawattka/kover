from __future__ import annotations

from typing import (
    List,
    Optional,
    TYPE_CHECKING,
    Union,
    Sequence
)

from .collection import Collection
from .typings import xJsonT
from .session import Transaction
from .models import User
from .schema import filter_non_null

if TYPE_CHECKING:
    from client import Kover


class Database:
    def __init__(self, name: str, client: Kover) -> None:
        self.name = name
        self.client = client

    def get_collection(self, name: str) -> Collection:
        return Collection(name=name, database=self)

    def __getattr__(self, name: str) -> Collection:
        return self.get_collection(name=name)

    async def list_collections(
        self,
        filter: Optional[xJsonT] = None,
        name_only: bool = False
    ) -> List[Collection]:
        request = await self.command({
            "listCollections": 1.0,
            "filter": filter or {}
        })
        return [Collection(
            name=x["name"],
            database=self,
            options=x["options"],
            info=x["info"]
        ) if not name_only else x["name"]
            for x in request["cursor"]["firstBatch"]
        ]

    async def create_collection(
        self,
        name: str,
        params: Optional[xJsonT] = None
    ) -> Collection:
        await self.command({
            "create": name, **(params or {})
        })
        return self.get_collection(name)

    async def drop_collection(self, name: str) -> None:
        await self.command({"drop": name})

    # https://gist.github.com/xandout/61d25df23a77236ab28236650f84ce6b
    async def create_user(
        self,
        name: str,
        password: str,
        roles: Optional[Sequence[Union[xJsonT, str]]] = None,
        custom_data: Optional[xJsonT] = None,
        mechanisms: List[str] = ["SCRAM-SHA-1", "SCRAM-SHA-256"],
        comment: Optional[str] = None,
        root: bool = False
    ) -> User:
        if root is True and roles is None:
            roles = [
                {'role': 'userAdminAnyDatabase', 'db': "admin"},
                {'role': 'root', 'db': "admin"},
                {'role': 'readWriteAnyDatabase', 'db': "admin"}
            ]
        if roles is None:
            raise Exception("You need to specify user roles.")
        command = filter_non_null({
            "createUser": name,
            "pwd": password,
            "mechanisms": mechanisms,
            "roles": roles,
            "customData": custom_data,
            "comment": comment
        })
        await self.command(command)
        found = await self.users_info(
            query=name,
            show_credentials=True,
            show_custom_data=True,
            show_privileges=True
        )
        return found[0]

    async def users_info(
        self,
        query: Optional[Union[str, float, xJsonT, List[xJsonT]]] = None,
        show_credentials: bool = False,
        show_custom_data: bool = False,
        show_privileges: bool = False,
        show_auth_restrictions: bool = False,
        filter: Optional[xJsonT] = None,
        comment: Optional[str] = None
    ) -> List[User]:
        if query is None:
            query = 1.0
        command = filter_non_null({
            "usersInfo": query,
            "showCredentials": show_credentials,
            "showCustomData": show_custom_data,
            "showPrivileges": show_privileges,
            "showAuthenticationRestrictions": show_auth_restrictions,
            "filter": filter,
            "comment": comment
        })
        request = await self.command(command)
        return [User.from_json(x) for x in request["users"]]

    async def drop_user(
        self,
        name: str,
        comment: Optional[str] = None
    ) -> None:
        command = filter_non_null({
            "dropUser": name,
            "comment": comment
        })
        await self.command(command)

    async def grant_roles_to_user(
        self,
        username: str,
        roles: List[Union[str, xJsonT]]
    ) -> None:
        await self.command({
            "grantRolesToUser": username,
            "roles": roles
        })

    async def command(
        self,
        doc: xJsonT,
        transaction: Optional[Transaction] = None
    ) -> xJsonT:
        return await self.client.socket.request(
            doc=doc,
            transaction=transaction,
            db_name=self.name
        )

    async def ping(self) -> bool:
        r = await self.command({
            "ping": 1.0
        })
        return r["ok"] == 1.0
