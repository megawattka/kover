from __future__ import annotations

import datetime
from enum import Enum
from dataclasses import field, dataclass, asdict, is_dataclass
from typing import List, Literal, Optional, Union, Any

from bson import Binary

from .typings import COMPRESSION_T, xJsonT
from .enums import CollationStrength, IndexDirection, IndexType


@dataclass
class AsDictMixin:
    def _convert_enums(self, obj: Any) -> Any:
        if isinstance(obj, Enum):
            return obj.value
        elif isinstance(obj, dict):
            return {k: self._convert_enums(v) for k, v in obj.items()}  # type: ignore  # noqa: E501
        elif isinstance(obj, list):
            return [self._convert_enums(v) for v in obj]  # type: ignore
        elif is_dataclass(obj):
            return self._convert_enums(asdict(obj))  # type: ignore
        return obj

    def to_dict(self) -> xJsonT:
        serialized = self._convert_enums(self)
        return {k: v for k, v in serialized.items() if v is not None}


@dataclass
class HelloResult(AsDictMixin):
    local_time: datetime.datetime
    connection_id: int
    read_only: bool
    mechanisms: Optional[List[str]] = field(default=None)
    compression: Optional[COMPRESSION_T] = field(default=None)
    requires_auth: bool = field(init=False, repr=False)

    def __post_init__(self):
        self.requires_auth = self.mechanisms is not None \
            and len(self.mechanisms) > 0


@dataclass
class BuildInfo(AsDictMixin):
    version: str
    git_version: str
    allocator: str
    js_engine: str
    version_array: list[int]
    openssl: str
    debug: bool
    max_bson_obj_size: int
    storage_engines: list[str]


@dataclass
class User(AsDictMixin):
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
@dataclass
class Index(AsDictMixin):
    name: str  # any index name e.g my_index
    key: dict[
        str,
        Union[IndexType, IndexDirection]
    ]
    unique: bool = False
    hidden: bool = False


# https://www.mongodb.com/docs/manual/reference/collation/
@dataclass
class Collation(AsDictMixin):
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
@dataclass
class Update(AsDictMixin):
    q: xJsonT
    u: xJsonT
    c: Optional[xJsonT] = None
    upsert: bool = False
    multi: bool = False
    collation: Optional[Collation] = None
    array_filters: Optional[xJsonT] = None
    hint: Optional[str] = None


# https://www.mongodb.com/docs/manual/reference/command/delete/#syntax
@dataclass
class Delete(AsDictMixin):
    q: xJsonT
    limit: Literal[0, 1]
    collation: Optional[Collation] = None
    hint: Optional[Union[xJsonT, str]] = None


# https://www.mongodb.com/docs/manual/reference/write-concern/
@dataclass
class WriteConcern(AsDictMixin):
    w: Union[str, int] = "majority"
    j: Optional[bool] = None
    wtimeout: int = 0


# https://www.mongodb.com/docs/manual/reference/read-concern/
@dataclass
class ReadConcern(AsDictMixin):
    level: Literal[
        "local",
        "available",
        "majority",
        "linearizable",
        "snapshot"
    ] = "local"
