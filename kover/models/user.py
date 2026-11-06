"""MongoDB user document."""

from typing import Any, Literal

from bson import Binary  # ruff: ignore[typing-only-third-party-import]
from pydantic import BaseModel, Field


class User(BaseModel):
    """Represents a MongoDB user document."""

    user_id: Binary = Field(repr=False)
    username: str = Field(alias="user")
    db_name: str = Field(alias="db")
    mechanisms: list[
        Literal["SCRAM-SHA-1", "SCRAM-SHA-256"]
    ] = Field(repr=False)
    credentials: dict[str, Any] = Field(
        repr=False,
        default_factory=dict[str, Any],
    )
    roles: list[dict[str, Any]]
    authentication_restrictions: list[dict[str, Any]] = Field(
        repr=False, default_factory=list[dict[str, Any]],
    )
    inherited_privileges: list[dict[str, Any]] = Field(
        repr=False, default_factory=list[dict[str, Any]],
    )
    custom_data: dict[str, Any] = Field(
        repr=False, default_factory=dict[str, Any],
    )
