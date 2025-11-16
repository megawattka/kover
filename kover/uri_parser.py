"""Uri parser functionality for Kover."""

from __future__ import annotations

from pydantic import Field
from pymongo.uri_parser import parse_uri as _parse_uri

from .internals.mixins import ModelMixin as _ModelMixin
from .network import AuthCredentials
from .typings import xJsonT  # noqa: TC001


class ParsedUri(_ModelMixin):
    """Represents a parsed MongoDB URI."""

    node_list: list[tuple[str, int]] = Field(alias="nodelist")
    username: str | None
    password: str | None
    database: str | None
    collection: str | None
    options: xJsonT
    fqdn: str | None

    @property
    def credentials(self) -> AuthCredentials | None:
        """Return credentials based on username and password."""
        if self.username is None or self.password is None:
            return None
        return AuthCredentials(
            username=self.username,
            password=self.password,
        )


def parse_uri(uri: str) -> ParsedUri:
    """Pymongo parse uri wrapper.

    Returns:
        ParsedUri object
    """
    parsed = _parse_uri(uri=uri)
    return ParsedUri.model_validate(parsed)
