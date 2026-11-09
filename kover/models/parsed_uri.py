"""Parsed uri model for kover."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, Field, field_validator

from .credentials import AuthCredentials

if TYPE_CHECKING:
    from pydantic import ValidationInfo

_EXTERNAL_MECHANISMS: Final[set[str]] = {
    "MONGODB-X509",
    "MONGODB-AWS",
    "GSSAPI",
    "MONGODB-OIDC",
}


def auth_database(options: dict[str, Any], database: str | None) -> str:
    """Return the mechanism-specific default authentication database.

    Raises:
        ValueError: If an external mechanism specifies another authSource.
    """
    mechanism = options.get("authMechanism")
    if mechanism in _EXTERNAL_MECHANISMS:
        if options.get("authSource", "$external") != "$external":
            raise ValueError(
                "This authMechanism requires authSource=$external",
            )
        return "$external"
    default = "$external" if mechanism == "PLAIN" else "admin"
    return options.get("authSource", database or default)


class ParsedUri(BaseModel):
    """Represents a parsed MongoDB URI."""

    node_list: list[tuple[str, int]] = Field(alias="nodelist")
    username: str | None
    password: str | None = Field(repr=False)
    database: str | None
    collection: str | None
    options: dict[str, Any]
    fqdn: str | None

    @property
    def credentials(self) -> AuthCredentials | None:
        """Build credentials, treating an omitted password as empty."""
        if self.username is None:
            return None

        return AuthCredentials(
            username=self.username,
            password=self.password or "",
            auth_database=auth_database(self.options, self.database),
        )

    @field_validator("options", mode="after")
    @classmethod
    def _validate_auth_database(
        cls,
        options: dict[str, Any],
        info: ValidationInfo,
    ) -> dict[str, Any]:
        auth_database(options, info.data.get("database"))
        return options
