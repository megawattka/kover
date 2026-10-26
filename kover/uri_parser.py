"""Uri parser functionality for Kover."""

from __future__ import annotations

from pydantic import Field
from pymongo.asynchronous.uri_parser import parse_uri as _parse_uri

from .mixins import ModelMixin as _ModelMixin
from .network import AuthCredentials
from .typings import JsonT  # ruff: ignore[typing-only-first-party-import]


class ParsedUri(_ModelMixin):
    """Represents a parsed MongoDB URI."""

    node_list: list[tuple[str, int]] = Field(alias="nodelist")
    username: str | None
    password: str | None
    database: str | None
    collection: str | None
    options: JsonT
    fqdn: str | None

    @property
    def credentials(self) -> AuthCredentials | None:
        """Use credentials based on username and password."""
        if self.username is None or self.password is None:
            return None

        return AuthCredentials(
            username=self.username,
            password=self.password,
        )


async def parse_uri(uri: str) -> ParsedUri:
    """Pymongo parse uri wrapper.

    Returns:
        ParsedUri object
    """
    parsed = await _parse_uri(uri=uri)
    return ParsedUri.model_validate(parsed)
