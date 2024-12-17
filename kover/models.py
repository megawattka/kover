from __future__ import annotations

import datetime
from typing import List, Literal, Optional, Union

from bson import Binary
from attrs import field, define, fields

from .typings import COMPRESSION_T, xJsonT
from .enums import CollationStrength, IndexDirection, IndexType
from .schema import filter_non_null, to_camel_case, maybe_enum_value


# TODO: refactor
class Serializable:
    # TODO: make it recursive
    def to_dict(self) -> xJsonT:
        return filter_non_null({
            to_camel_case(attrib.name): maybe_enum_value(
                getattr(self, attrib.name)
            )
            for attrib in fields(self.__class__)
        })


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
class BuildInfo(Serializable):
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
class User(Serializable):
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
            credentials=document.get("credentials", {}),
            roles=document["roles"],
            auth_restrictions=document.get("authenticationRestrictions", []),
            privileges=document.get("inheritedPrivileges", []),
            custom_data=document.get("customData", {})
        )


# https://www.mongodb.com/docs/manual/reference/command/createIndexes/#example
@define
class Index(Serializable):
    name: str  # any index name e.g my_index
    key: dict[
        str,
        Union[IndexType, IndexDirection]
    ]
    unique: bool = False
    hidden: bool = False


# https://www.mongodb.com/docs/manual/reference/collation/
@define
class Collation(Serializable):
    locale: Optional[str] = None
    case_level: bool = False
    case_first: Literal["lower", "upper", "off"] = "off"
    strength: CollationStrength = CollationStrength.TERTIARY
    numeric_ordering: bool = False
    alternate: Literal["non-ignorable", "shifted"] = "non-ignorable"
    max_variable: Optional[Literal["punct", "space"]] = None
    backwards: bool = False
    normalization: bool = False


# https://www.mongodb.com/docs/manual/reference/command/update/#syntax
@define
class Update(Serializable):
    q: xJsonT
    u: xJsonT
    c: Optional[xJsonT] = None
    upsert: bool = False
    multi: bool = False
    collation: Optional[Collation] = None
    array_filters: Optional[xJsonT] = None
    hint: Optional[str] = None


# https://www.mongodb.com/docs/manual/reference/write-concern/
@define
class WriteConcern(Serializable):
    w: Union[str, int] = "majority"
    j: Optional[bool] = None
    wtimeout: int = 0


# https://www.mongodb.com/docs/manual/reference/read-concern/
@define
class ReadConcern(Serializable):
    level: Literal[
        "local",
        "available",
        "majority",
        "linearizable",
        "snapshot"
    ] = "local"
