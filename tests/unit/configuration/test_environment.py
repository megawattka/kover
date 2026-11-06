from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from kover.configuration.environment import (
    get_runtime_environment,
    read_auth_credentials_from_env,
    resolve_auth_db_from_env,
)
from kover.exceptions import CredentialsException
from kover.models.credentials import AuthCredentials


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({}, None),
        ({"MONGO_USER": "user"}, CredentialsException),
        ({"MONGO_PASSWORD": "secret"}, CredentialsException),
    ],
)
def test_environment_credentials_pair_validation(
    environment: dict[str, str],
    expected: type[Exception] | None,
) -> None:
    if expected is not None:
        with pytest.raises(expected):
            read_auth_credentials_from_env(environ=environment)
    else:
        assert read_auth_credentials_from_env(environ=environment) is None


def test_environment_snapshot_preserves_values_and_auth_database() -> None:
    environment = {
        "MONGO_USER": "",
        "MONGO_PASSWORD": "",
        "MONGO_AUTH_DB": "users",
    }
    fields = read_auth_credentials_from_env(environ=environment)
    assert fields is not None
    assert fields == {
        "username": "",
        "password": "",
        "auth_database": "users",
    }
    environment["MONGO_USER"] = "changed"
    assert not fields["username"]
    assert resolve_auth_db_from_env(environ={}) == "admin"
    assert (
        resolve_auth_db_from_env(
            key="OTHER",
            default="fallback",
            environ={},
        )
        == "fallback"
    )


def test_auth_credentials_environment_and_md5_format() -> None:
    environment = {
        "MONGO_USER": "user",
        "MONGO_PASSWORD": "secret",
        "MONGO_AUTH_DB": "auth",
    }
    with patch.dict(os.environ, environment, clear=True):
        credentials = AuthCredentials.from_environ()
    assert credentials is not None
    assert credentials.auth_database == "auth"
    assert credentials.md5_hash() == b"3760b983c2cb989030641919481b6978"
    document: dict[str, object] = {}
    credentials.apply_to(document)
    assert document == {"saslSupportedMechs": "auth.user"}
    assert "secret" not in repr(credentials)


def test_credentials_from_environ_missing_and_partial_pair() -> None:
    with patch.dict(os.environ, {}, clear=True):
        assert AuthCredentials.from_environ() is None
    with (
        patch.dict(os.environ, {"MONGO_USER": "user"}, clear=True),
        pytest.raises(CredentialsException),
    ):
        AuthCredentials.from_environ()


def test_runtime_environment_fields_exclude_hostnames_and_secrets() -> None:
    runtime = get_runtime_environment()
    assert set(runtime) == {"os", "platform"}
    assert set(runtime["os"]) == {"type", "name", "architecture", "version"}
    assert runtime["platform"]
