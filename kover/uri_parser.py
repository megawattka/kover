from __future__ import annotations

from collections import UserDict
from typing import Any, TypeVar
from urllib.parse import parse_qsl, urlparse
import warnings

from pydantic import Field

from ._internals._mixins import ModelMixin as _ModelMixin
from .network import AuthCredentials
from .typings import COMPRESSION_T, xJsonT  # noqa: TC001

V = TypeVar("V")

_BOOL_TRUE = {"1", "y", "t", "true"}
_BOOL_FALSE = {"no", "-1", "0", "n", "f", "false"}
_BOOL_VALUES = _BOOL_FALSE.union(_BOOL_TRUE)


class CaseInsensitiveDict(UserDict[str, V]):
    """A basic implementation for case insensetive dict, used for qs args."""

    def __setitem__(self, key: str, value: V) -> None:
        super().__setitem__(key.lower(), value)

    def __getitem__(self, key: str) -> V:
        return super().__getitem__(key.lower())

    def get(self, key: str, default: ... = None) -> V:
        """https://python-reference.readthedocs.io/en/latest/docs/dict/get.html."""
        return super().get(key, default=default)


def _bool_from_str(key: str, value: str) -> bool:
    # https://github.com/mongodb/specifications/blob/master/source/connection-string/connection-string-spec.md#values
    if value in _BOOL_VALUES and value not in {"true", "false"}:
        warnings.warn(
            f'Deprecated boolean value for "{key}": "{value}", '
            f'please update to "{key}=true"',
            UserWarning,  # DeprecationWarning
            stacklevel=0,
        )
    if value in _BOOL_TRUE:
        return True
    if value in _BOOL_FALSE:
        return False
    raise ValueError(f"Unknown boolean value: {value}")


class ParsedUri(_ModelMixin):
    """Represents a parsed MongoDB URI."""

    tls: bool
    hostname: str
    port: int
    write_concern: str | int = Field(alias="write_concern")
    credentials: AuthCredentials | None
    compressors: COMPRESSION_T = Field(default_factory=COMPRESSION_T)
    application: xJsonT | None = None


def is_valid_uri(uri: str) -> bool:
    """Check if the given URI is valid."""
    try:
        parts = urlparse(uri)
        port = parts.port if parts.port is not None else 0
    except (ValueError, TypeError):
        return False
    if parts.hostname is None or len(parts.hostname) == 0:
        return False
    if parts.hostname and (port == 0):
        return False
    if parts.scheme not in {"mongodb", "mongodb+srv"}:
        return False
    return not (parts.scheme == "mongodb+srv" and port != 27017)


def parse_uri(uri: str) -> ParsedUri:
    """Parse given uri and return parsed args."""
    if not is_valid_uri(uri):
        raise ValueError(f"Invalid URI: {uri}")

    parts = urlparse(uri)
    parameters: CaseInsensitiveDict[Any] = CaseInsensitiveDict()

    parsed = parse_qsl(parts.query)
    for k, v in parsed:
        parameters[k] = v

    tls = _bool_from_str("tls", parameters.get("tls", "true"))
    app_name = parameters.get("appName")
    port = parts.port or 27017
    write_concern = parameters.get("w", "majority")

    compressors = parameters.get("compressors")
    if compressors is not None:
        compressors = compressors.split(",")

    credentials = AuthCredentials.from_parts(parts)
    application = {"name": app_name}
    assert parts.hostname is not None  # for pyright

    return ParsedUri(
        hostname=parts.hostname,
        port=port,
        credentials=credentials,
        compressors=compressors,
        tls=tls,
        write_concern=write_concern,
        application=application,
    )
