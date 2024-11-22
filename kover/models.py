from __future__ import annotations

import datetime
from typing import List, Literal, Optional, Union

from bson import Binary
from attrs import field, define, asdict

from .typings import COMPRESSION_T, xJsonT
from .enums import IndexType, IndexDirection


@define
class HelloResult:
    local_time: datetime.datetime
    connection_id: int
    read_only: bool
    mechanisms: Optional[List[str]] = field(default=None)
    compression: COMPRESSION_T = field(default=None)
    requires_auth: bool = field(init=False, repr=False)

    def __attrs_post_init__(self) -> None:
        self.requires_auth = self.mechanisms is not None \
            and len(self.mechanisms) > 0


@define
class BuildInfo:
    version: str
    git_version: str
    allocator: str
    js_engine: str
    version_array: list[int]
    openssl: str
    debug: bool
    max_bson_obj_size: int
    storage_engines: list[str]


@define
class User:
    user_id: Binary = field(repr=False)
    username: str
    db_name: str
    mechanisms: List[
        Literal['SCRAM-SHA-1', 'SCRAM-SHA-256']
    ] = field(repr=False)
    credentials: xJsonT = field(repr=False)
    roles: List[xJsonT]
    auth_restrictions: List[xJsonT] = field(repr=False)
    privileges: List[xJsonT] = field(repr=False)
    custom_data: xJsonT = field(repr=False)

    @classmethod
    def from_json(cls, document: xJsonT) -> User:
        return cls(
            user_id=document["userId"],
            username=document["user"],
            db_name=document["db"],
            mechanisms=document["mechanisms"],
            credentials=document["credentials"],
            roles=document["roles"],
            auth_restrictions=document.get("authenticationRestrictions", []),
            privileges=document.get("inheritedPrivileges", []),
            custom_data=document.get("customData", {})
        )


# https://www.mongodb.com/docs/manual/reference/command/createIndexes/#example
@define
class Index:
    name: str  # any index name e.g my_index
    keys: list[str]  # keys that are being indexed
    unique: bool = False
    hidden: bool = False
    index_strategy: Union[IndexDirection, IndexType] = field(
        repr=False,
        default=IndexDirection.ASCENDING
    )

    def to_dict(self) -> xJsonT:
        payload = asdict(self)
        payload["key"] = {
            key: self.index_strategy.value
            for key in payload.pop("keys")
        }
        return payload
