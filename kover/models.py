from __future__ import annotations

import datetime  # noqa: TC003
from typing import Literal

from bson import Binary, ObjectId  # noqa: TC002
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from .enums import CollationStrength, IndexDirection, IndexType  # noqa: TC001
from .typings import COMPRESSION_T, xJsonT


class _CamelAliasedModel(BaseModel):
    """Base class for all models with camel case fields."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="ignore",
        arbitrary_types_allowed=True,
        use_enum_values=True,
    )

    def to_dict(self) -> xJsonT:
        """Convert the model to a dictionary with camel case keys."""
        return self.model_dump(by_alias=True, exclude_none=True)


class HelloResult(_CamelAliasedModel):
    """Represents the result of a hello command."""

    local_time: datetime.datetime
    connection_id: int
    read_only: bool
    sasl_supported_mechs: list[str] = Field(default_factory=list[str])
    compression: COMPRESSION_T = Field(default_factory=COMPRESSION_T)

    @property
    def requires_auth(self) -> bool:
        """Check if the server requires authentication."""
        return len(self.sasl_supported_mechs) > 0


class BuildInfo(_CamelAliasedModel):
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

    @field_validator("openssl")
    @classmethod
    def validate_openssl(cls, value: xJsonT) -> str:
        """Validate the OpenSSL version."""
        return value["running"]


class User(_CamelAliasedModel):
    """Represents a MongoDB user document."""

    user_id: Binary = Field(repr=False)
    username: str = Field(alias="user")
    db_name: str = Field(alias="db")
    mechanisms: list[
        Literal["SCRAM-SHA-1", "SCRAM-SHA-256"]
    ] = Field(repr=False)
    credentials: xJsonT = Field(repr=False, default_factory=xJsonT)
    roles: list[xJsonT]
    authentication_restrictions: list[xJsonT] = Field(
        repr=False, default_factory=list[xJsonT],
    )
    inherited_privileges: list[xJsonT] = Field(
        repr=False, default_factory=list[xJsonT],
    )
    custom_data: xJsonT = Field(
        repr=False, default_factory=xJsonT,
    )


# https://www.mongodb.com/docs/manual/reference/command/createIndexes/#example
class Index(_CamelAliasedModel):
    """Represents a MongoDB index document."""

    name: str  # any index name e.g my_index
    key: dict[str, IndexType | IndexDirection]
    unique: bool = Field(default=False)
    hidden: bool = Field(default=False)


# https://www.mongodb.com/docs/manual/reference/collation/
class Collation(_CamelAliasedModel):
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


# https://www.mongodb.com/docs/manual/reference/command/update/#syntax
class Update(_CamelAliasedModel):
    """Represents a MongoDB update document."""

    def __init__(
        self,
        q: xJsonT,
        u: xJsonT,
        c: xJsonT | None = None,
        /,
        **kwargs: object,
    ) -> None:
        BaseModel.__init__(self, q=q, u=u, c=c, **kwargs)

    q: xJsonT
    u: xJsonT
    c: xJsonT | None = None
    upsert: bool = False
    multi: bool = False
    collation: Collation | None = None
    array_filters: xJsonT | None = None
    hint: str | None = None


# https://www.mongodb.com/docs/manual/reference/command/delete/#syntax
class Delete(_CamelAliasedModel):
    """Represents a MongoDB delete document."""

    def __init__(self, q: xJsonT, /, **kwargs: object) -> None:
        BaseModel.__init__(self, q=q, **kwargs)

    q: xJsonT
    limit: Literal[0, 1]
    collation: Collation | None = None
    hint: xJsonT | str | None = None


# https://www.mongodb.com/docs/manual/reference/write-concern/
class WriteConcern(_CamelAliasedModel):
    """Represents a MongoDB write concern document."""

    w: str | int = "majority"
    j: bool | None = None
    wtimeout: int = 0


# https://www.mongodb.com/docs/manual/reference/read-concern/
class ReadConcern(_CamelAliasedModel):
    """Represents a MongoDB read concern document."""

    level: Literal[
        "local",
        "available",
        "majority",
        "linearizable",
        "snapshot",
    ] = "local"


# https://www.mongodb.com/docs/manual/reference/replica-configuration/#members
class ReplicaSetMember(_CamelAliasedModel):
    """Represents a MongoDB replica set member document."""

    member_id: int = Field(serialization_alias="_id", alias="member_id")
    host: str
    arbiter_only: bool = Field(default=False)
    build_indexes: bool = Field(default=True)
    hidden: bool = Field(default=False)
    priority: int = Field(default=1)
    tags: xJsonT | None = Field(default=None)
    secondary_delay_secs: int = Field(default=0)
    votes: int = Field(default=1)


# https://www.mongodb.com/docs/manual/reference/replica-configuration/#settings
class ReplicaSetConfigSettings(_CamelAliasedModel):
    """Represents a MongoDB replica set settings document."""

    replica_set_id: ObjectId
    chaining_allowed: bool = Field(default=True)
    get_last_error_modes: xJsonT | None = Field(default=None)
    heartbeat_timeout_secs: int = Field(default=10)
    election_timeout_millis: int = Field(default=10000)
    catch_up_timeout_millis: int = Field(default=-1)
    catch_up_takeover_delay_millis: int = Field(default=-1)


# https://www.mongodb.com/docs/manual/reference/replica-configuration/#replica-set-configuration-document-example
class ReplicaSetConfig(_CamelAliasedModel):
    """Represents a MongoDB replica set configuration document."""

    rs_name: str = Field(serialization_alias="_id", alias="rs_name")
    version: int
    term: int
    members: list[ReplicaSetMember]
    configsvr: bool = Field(default=False)
    protocol_version: int = Field(default=1)
    write_concern_majority_journal_default: bool = Field(default=True)
    settings: ReplicaSetConfigSettings | None = None

    @classmethod
    def default(cls) -> ReplicaSetConfig:
        """Create a default replica set configuration."""
        return cls(
            rs_name="rs0",
            version=1,
            term=0,
            members=[ReplicaSetMember(member_id=0, host="127.0.0.1:27017")],
        )
