"""Other models, that ill sort in future."""

from __future__ import annotations

import datetime as dt  # ruff: ignore[typing-only-standard-library-import]
from typing import Literal, NotRequired, Self, TypedDict, Unpack

from bson import Binary  # ruff: ignore[typing-only-third-party-import]
from pydantic import BaseModel, Field, model_validator
from pydantic.functional_validators import (
    ModelWrapValidatorHandler,  # ruff: ignore[typing-only-third-party-import]
)

from ..enums import CollationStrength, IndexDirection, IndexType  # ruff: ignore[typing-only-first-party-import]
from ..mixins import ModelMixin as _ModelMixin
from ..typings import AuthTypesT, CompressionT, DictT


class HelloResult(_ModelMixin):
    """Represents the result of a hello command."""

    me: str | None = Field(default=None)
    msg: str | None = Field(default=None)
    local_time: dt.datetime
    connection_id: int
    read_only: bool | None = None
    sasl_supported_mechs: list[AuthTypesT] = Field(
        default_factory=list[AuthTypesT])
    compression: CompressionT = Field(default_factory=CompressionT)
    is_primary: bool = Field(alias="isWritablePrimary")
    primary_node: str | None = Field(default=None, alias="primary")
    hosts: list[str] | None = Field(default=None)
    passives: list[str] = Field(default_factory=list)
    arbiters: list[str] = Field(default_factory=list)
    secondary: bool = False
    arbiter_only: bool = False
    hidden: bool = False
    is_replica_set: bool = Field(default=False, alias="isreplicaset")
    set_name: str | None = Field(default=None)
    set_version: int | None = Field(default=None)
    tags: dict[str, str] = Field(default_factory=dict)
    last_write: DictT = Field(default_factory=dict)

    @property
    def requires_auth(self) -> bool:
        """Check if the server requires authentication."""
        return len(self.sasl_supported_mechs) > 0

    def get_auth_mechanism(self) -> AuthTypesT | None:
        """Returns a auth mechanism from result mechanisms."""
        if self.requires_auth:
            if "SCRAM-SHA-256" in self.sasl_supported_mechs:
                return "SCRAM-SHA-256"

            if "SCRAM-SHA-1" in self.sasl_supported_mechs:
                return "SCRAM-SHA-1"
        return None


class BuildInfo(_ModelMixin):
    """Represents the result of a buildInfo command."""

    version: str
    git_version: str
    allocator: str
    javascript_engine: str
    version_array: list[int]
    openssl: str
    debug: bool
    max_bson_object_size: int
    storage_engines: list[str]

    @model_validator(mode="wrap")
    @classmethod
    def _validate_openssl(
        cls,
        data: DictT,
        wrap: ModelWrapValidatorHandler[Self],
    ) -> Self:
        data["openssl"] = data["openssl"]["running"]
        return wrap(data)


class User(_ModelMixin):
    """Represents a MongoDB user document."""

    user_id: Binary = Field(repr=False)
    username: str = Field(alias="user")
    db_name: str = Field(alias="db")
    mechanisms: list[
        Literal["SCRAM-SHA-1", "SCRAM-SHA-256"]
    ] = Field(repr=False)
    credentials: DictT = Field(repr=False, default_factory=DictT)
    roles: list[DictT]
    authentication_restrictions: list[DictT] = Field(
        repr=False, default_factory=list[DictT],
    )
    inherited_privileges: list[DictT] = Field(
        repr=False, default_factory=list[DictT],
    )
    custom_data: DictT = Field(
        repr=False, default_factory=DictT,
    )


class _IndexKwargs(TypedDict):
    unique: NotRequired[bool]
    hidden: NotRequired[bool]


# https://www.mongodb.com/docs/manual/reference/command/createIndexes/#example
class Index(_ModelMixin):
    """Represents a MongoDB index document."""

    def __init__(
        self, name: str,
        key: dict[str, IndexType | IndexDirection],
        **kwargs: Unpack[_IndexKwargs],
    ) -> None:
        BaseModel.__init__(self, name=name, key=key, **kwargs)

    name: str
    key: dict[str, IndexType | IndexDirection]
    unique: bool = Field(default=False)
    hidden: bool = Field(default=False)


# https://www.mongodb.com/docs/manual/reference/collation/
class Collation(_ModelMixin):
    """Represents a MongoDB collation document."""

    locale: str | None = None
    case_level: bool = False
    case_first: Literal["lower", "upper", "off"] = "off"
    strength: CollationStrength = CollationStrength.TERTIARY
    numeric_ordering: bool = False
    alternate: Literal["non-ignorable", "shifted"] = "non-ignorable"
    max_variable: Literal["punct", "space"] | None = None
    backwards: bool = False
    normalization: bool = False


# https://www.mongodb.com/docs/manual/reference/write-concern/
class WriteConcern(_ModelMixin):
    """Represents a MongoDB write concern document."""

    w: str | int = "majority"
    j: bool | None = None
    wtimeout: int = 0

    def to_dict(self) -> DictT:
        """Return the write concern document."""
        return {
            "w": self.w,
            **({"j": self.j} if self.j is not None else {}),
            **({"wtimeout": self.wtimeout} if self.wtimeout else {}),
        }


# https://www.mongodb.com/docs/manual/reference/read-concern/
class ReadConcern(_ModelMixin):
    """Represents a MongoDB read concern document."""

    level: Literal[
        "local",
        "available",
        "majority",
        "linearizable",
        "snapshot",
    ] = "local"
