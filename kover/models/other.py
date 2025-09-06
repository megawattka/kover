"""Other models, that ill sort in future."""

from __future__ import annotations

import datetime  # noqa: TC003
import secrets
from typing import Literal

from pydantic import Field, model_validator
from pydantic.functional_validators import (
    ModelWrapValidatorHandler,  # noqa: TC002
)
from typing_extensions import Self

from .._internals._mixins import ModelMixin as _ModelMixin
from ..bson import Binary  # noqa: TC001
from ..enums import CollationStrength, IndexDirection, IndexType  # noqa: TC001
from ..typings import COMPRESSION_T, AuthTypesT, xJsonT


class HelloResult(_ModelMixin):
    """Represents the result of a hello command."""

    me: str
    local_time: datetime.datetime
    connection_id: int
    read_only: bool
    sasl_supported_mechs: list[AuthTypesT] = Field(
        default_factory=list[AuthTypesT])
    compression: COMPRESSION_T = Field(default_factory=COMPRESSION_T)
    is_primary: bool = Field(alias="isWritablePrimary")
    primary_node: str | None = Field(default=None, alias="primary")
    hosts: list[str] | None = None
    set_name: str | None = None
    set_version: int | None = None

    @property
    def requires_auth(self) -> bool:
        """Check if the server requires authentication."""
        return len(self.sasl_supported_mechs) > 0

    def get_auth_mechanism(self) -> AuthTypesT | None:
        """Returns a random mechanism from result mechanisms."""
        if self.requires_auth:
            return secrets.choice(self.sasl_supported_mechs)
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
        data: xJsonT,
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
class Index(_ModelMixin):
    """Represents a MongoDB index document."""

    name: str  # any index name e.g my_index
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
