from __future__ import annotations

from base64 import b64encode
from datetime import UTC, datetime
import hashlib
import hmac
import os
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from bson import Binary
import pytest

from kover.exceptions import CredentialsException
from kover.models import HelloResult
from kover.network.auth import Auth, AuthCredentials
from kover.network.connection import Connection

if TYPE_CHECKING:
    from kover.typings import DictT


@pytest.mark.parametrize(
    ("user", "password"),
    [(None, None), ("user", None), (None, "password"), ("user", "password")],
)
def test_credentials_environment(
    user: str | None, password: str | None,
) -> None:
    environment = {"MONGO_AUTH_DB": "auth"}
    if user is not None:
        environment["MONGO_USER"] = user
    if password is not None:
        environment["MONGO_PASSWORD"] = password
    with patch.dict(os.environ, environment, clear=True):
        if (user is None) != (password is None):
            with pytest.raises(CredentialsException):
                AuthCredentials.from_environ()
        elif user is None:
            assert AuthCredentials.from_environ() is None
        else:
            credentials = AuthCredentials.from_environ()
            assert credentials is not None
            assert credentials.auth_database == "auth"
            assert credentials.username == "user"
            document: DictT = {}
            credentials.apply_to(document)
            assert document == {"saslSupportedMechs": "auth.user"}


@pytest.mark.parametrize(
    ("mechanisms", "expected"),
    [
        ([], None),
        (["SCRAM-SHA-1"], "SCRAM-SHA-1"),
        (["SCRAM-SHA-1", "SCRAM-SHA-256"], "SCRAM-SHA-256"),
    ],
)
def test_hello_auth_mechanism_preference(
    mechanisms: list[str], expected: str | None,
) -> None:
    hello = HelloResult.model_validate(
        {
            "localTime": datetime.now(UTC),
            "connectionId": 1,
            "isWritablePrimary": True,
            "saslSupportedMechs": mechanisms,
        },
    )
    assert hello.get_auth_mechanism() == expected
    assert hello.requires_auth == bool(mechanisms)


@pytest.mark.parametrize("mechanism", ["SCRAM-SHA-1", "SCRAM-SHA-256"])
async def test_scram_proof_and_server_signature(  # ruff: ignore[too-many-locals]
    mechanism: str,
) -> None:
    connection = MagicMock(spec=Connection)
    credentials = AuthCredentials(
        username="user,name=", password="password", auth_database="auth",
    )
    digest = "sha1" if mechanism.endswith("-1") else "sha256"
    password = credentials.md5_hash() if digest == "sha1" else b"password"
    nonce = b64encode(b"n" * 32)
    first_bare = b"n=user=2Cname=3D,r=" + nonce
    server_nonce = nonce + b"server"
    server_first = (
        b"r=" + server_nonce + b",s=" + b64encode(b"salt") + b",i=4097"
    )
    auth_message = b",".join(
        (first_bare, server_first, b"c=biws,r=" + server_nonce),
    )
    salted = hashlib.pbkdf2_hmac(digest, password, b"salt", 4097)
    client_key = hmac.digest(salted, b"Client Key", digest)
    server_key = hmac.digest(salted, b"Server Key", digest)
    signature = b64encode(hmac.digest(server_key, auth_message, digest))
    client_signature = hmac.digest(
        hashlib.new(digest, client_key).digest(), auth_message, digest,
    )
    expected_proof = b64encode(
        bytes(
            a ^ b
            for a, b in zip(client_key, client_signature, strict=True)
        ),
    )
    connection.command.side_effect = [
        {"payload": Binary(server_first), "conversationId": 7},
        {"payload": Binary(b"v=" + signature), "done": True},
    ]
    with patch("kover.network.auth.os.urandom", return_value=b"n" * 32):
        assert (
            await Auth(connection).create(mechanism, credentials) == signature
        )
    first = connection.command.await_args_list[0]
    assert first.kwargs["database"] == "auth"
    assert first.kwargs["document"]["payload"] == Binary(b"n,," + first_bare)
    continuation = connection.command.await_args_list[1]
    assert continuation.kwargs["database"] == "auth"
    final = continuation.args[0]
    assert final["conversationId"] == 7
    assert final["payload"] == Binary(
        b"c=biws,r=" + server_nonce + b",p=" + expected_proof,
    )


@pytest.mark.parametrize(
    ("failure", "match"),
    [
        ("mechanism", "Unknown"),
        ("iterations", "iteration"),
        ("nonce", "nonce"),
        ("unfinished", "not completed"),
        ("signature", "Digests"),
    ],
)
async def test_scram_rejects_invalid_server_conversation(
    failure: str, match: str,
) -> None:
    connection = MagicMock(spec=Connection)
    credentials = AuthCredentials(username="user", password="password")
    auth = Auth(connection)
    iterations = b"4096" if failure == "iterations" else b"4097"
    nonce = b"wrong" if failure == "nonce" else b"nonceserver"
    payload = b"r=" + nonce + b",s=" + b64encode(b"salt") + b",i=" + iterations
    connection.command.return_value = {
        "done": failure != "unfinished",
        "payload": Binary(b"v=invalid"),
    }
    with patch.object(
        auth,
        "_sasl_start",
        new=AsyncMock(return_value=(b"nonce", payload, b"n=user,r=nonce", 7)),
    ):
        error_type = RuntimeError if failure == "unfinished" else ValueError
        with pytest.raises(error_type, match=match):
            await auth.create(
                "unknown" if failure == "mechanism" else "SCRAM-SHA-256",
                credentials,
            )


def test_xor_rejects_mismatched_lengths() -> None:
    assert Auth.xor(b"\x01\x02", b"\x03\x04") == b"\x02\x06"
    with pytest.raises(ValueError, match="longer"):
        Auth.xor(b"a", b"ab")
