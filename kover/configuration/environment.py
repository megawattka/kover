"""Read process configuration and runtime information at a single boundary.

MongoDB authentication uses ``MONGO_USER``, ``MONGO_PASSWORD``, and optionally
``MONGO_AUTH_DB`` (default: ``admin``). Values are read on demand, never cached
at import time. Explicit URI authentication settings are resolved separately.

Readers accept an optional environment mapping so callers can resolve settings
without mutating the process environment. Empty strings are preserved as
explicit values; only missing keys count as absent credentials.
"""

from __future__ import annotations

import os
import platform
import sys
from typing import TYPE_CHECKING, TypedDict

from ..exceptions import CredentialsException

if TYPE_CHECKING:
    from collections.abc import Mapping


class AuthEnvironment(TypedDict):
    """Authentication fields ready for construction of a credentials model."""

    username: str
    password: str
    auth_database: str


class RuntimeEnvironment(TypedDict):
    """OS and Python metadata used in the MongoDB hello client document."""

    os: dict[str, str]
    platform: str


def resolve_auth_db_from_env(
    key: str = "MONGO_AUTH_DB",
    default: str = "admin",
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Read the authentication database, using the default for a missing key.

    Returns:
        The configured database name, unchanged.
    """
    source = os.environ if environ is None else environ
    return source.get(key, default)


def read_auth_credentials_from_env(
    *,
    environ: Mapping[str, str] | None = None,
) -> AuthEnvironment | None:
    """Resolve authentication from one snapshot of the environment.

    Returns:
        Credentials fields when both user and password are present, or
        ``None`` when both are missing. No credentials model is created here.

    Raises:
        CredentialsException: if username or password is missing
    """
    source = dict(os.environ if environ is None else environ)
    username = source.get("MONGO_USER")
    password = source.get("MONGO_PASSWORD")

    if username is None and password is None:
        return None

    if username is None or password is None:
        raise CredentialsException

    return {
        "username": username,
        "password": password,
        "auth_database": resolve_auth_db_from_env(environ=source),
    }


def get_runtime_environment() -> RuntimeEnvironment:
    """Collect host and interpreter metadata without application secrets.

    Returns:
        Fresh OS and Python metadata for the hello client document. Hostname
        and process environment variables are deliberately not included.
    """
    uname = platform.uname()
    implementation = sys.implementation
    version = ".".join(map(str, implementation.version))
    return {
        "os": {
            "type": os.name,
            "name": uname.system,
            "architecture": uname.machine,
            "version": uname.release,
        },
        "platform": implementation.name + " " + version,
    }
