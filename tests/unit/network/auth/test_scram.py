from __future__ import annotations

from base64 import b64encode
import hashlib
from hmac import HMAC
from unittest.mock import AsyncMock, patch

from bson import Binary
import pytest

from kover.models.credentials import AuthCredentials
from kover.network.auth.scram import MIN_ITERATIONS, ScramAuthenticator


def make_exchange(
    mechanism: str,
    credentials: AuthCredentials,
    *,
    done: bool = True,
    valid_signature: bool = True,
    iterations: int = MIN_ITERATIONS + 1,
) -> tuple[AsyncMock, bytes, bytes, bytes]:
    """Create deterministic SCRAM responses from a valid test server proof.

    Returns:
        Mock command callback and the expected client/server nonces/signature.
    """
    digest_name = "sha1" if mechanism == "SCRAM-SHA-1" else "sha256"
    digest = hashlib.sha1 if digest_name == "sha1" else hashlib.sha256
    password = (
        credentials.md5_hash()
        if digest_name == "sha1"
        else credentials.password.encode()
    )
    nonce = b64encode(b"client-nonce")
    server_nonce = nonce + b"server"
    salt = b"test-salt"
    server_first = (
        b"r=" + server_nonce + b",s=" + b64encode(salt)
        + b",i=" + str(iterations).encode()
    )
    first_bare = b"n=" + credentials.username.encode() + b",r=" + nonce
    final_without_proof = b"c=biws,r=" + server_nonce
    auth_message = b",".join((first_bare, server_first, final_without_proof))
    salted = hashlib.pbkdf2_hmac(digest_name, password, salt, iterations)
    server_key = HMAC(salted, b"Server Key", digest).digest()
    signature = b64encode(HMAC(server_key, auth_message, digest).digest())
    if not valid_signature:
        signature = b64encode(b"invalid-server-proof")
    command = AsyncMock(
        side_effect=[
            {"payload": Binary(server_first), "conversationId": 13},
            {"payload": Binary(b"v=" + signature), "done": done},
        ],
    )
    return command, nonce, server_nonce, signature


@pytest.mark.parametrize("mechanism", ["SCRAM-SHA-1", "SCRAM-SHA-256"])
async def test_scram_validates_server_and_sends_protocol_messages(
    mechanism: str,
) -> None:
    password = "test-pass"  # ruff: ignore[hardcoded-password-string]
    credentials = AuthCredentials(
        username="user",
        password=password,
        auth_database="auth",
    )
    command, nonce, server_nonce, signature = make_exchange(
        mechanism,
        credentials,
    )
    with patch(
        "kover.network.auth.scram.os.urandom",
        return_value=b"client-nonce",
    ):
        result = await ScramAuthenticator(command).authenticate(
            mechanism,
            credentials,
        )

    assert result == signature
    start = command.await_args_list[0]
    assert start.args[0]["saslStart"] == 1
    assert start.args[0]["mechanism"] == mechanism
    assert start.args[0]["payload"] == Binary(
        b"n,,n=user,r=" + nonce,
    )
    assert start.args[0]["options"] == {"skipEmptyExchange": True}
    assert start.kwargs["database"] == "auth"
    final = command.await_args_list[1]
    assert final.args[0]["conversationId"] == 13
    assert bytes(final.args[0]["payload"]).startswith(
        b"c=biws,r=" + server_nonce + b",p=",
    )


async def test_scram_rejects_invalid_mechanism_and_server_values() -> None:
    password = "test-pass"  # ruff: ignore[hardcoded-password-string]
    credentials = AuthCredentials(username="user", password=password)
    command = AsyncMock()
    authenticator = ScramAuthenticator(command)
    with pytest.raises(ValueError, match="unsupported authentication"):
        await authenticator.authenticate("PLAIN", credentials)
    command.assert_not_awaited()

    command, _, _, _ = make_exchange(
        "SCRAM-SHA-256", credentials,
    )
    bad_nonce_command = AsyncMock(return_value={
        "payload": Binary(
            b"r=wrong-server-nonce,s=c2FsdA==,i=4097",
        ),
    })
    with (
        patch(
            "kover.network.auth.scram.os.urandom",
            return_value=b"client-nonce",
        ),
        pytest.raises(ValueError, match="invalid nonce"),
    ):
        await ScramAuthenticator(bad_nonce_command).authenticate(
            "SCRAM-SHA-256",
            credentials,
        )

    command, _, _, _ = make_exchange(
        "SCRAM-SHA-256",
        credentials,
        iterations=MIN_ITERATIONS - 1,
    )
    with (
        patch(
            "kover.network.auth.scram.os.urandom",
            return_value=b"client-nonce",
        ),
        pytest.raises(ValueError, match="iteration count"),
    ):
        await ScramAuthenticator(command).authenticate(
            "SCRAM-SHA-256", credentials,
        )


async def test_scram_rejects_bad_proof_and_incomplete_exchange() -> None:
    password = "test-pass"  # ruff: ignore[hardcoded-password-string]
    credentials = AuthCredentials(username="user", password=password)
    command, _, _, _ = make_exchange(
        "SCRAM-SHA-256", credentials, valid_signature=False,
    )
    with (
        patch(
            "kover.network.auth.scram.os.urandom",
            return_value=b"client-nonce",
        ),
        pytest.raises(ValueError, match="signatures differ"),
    ):
        await ScramAuthenticator(command).authenticate(
            "SCRAM-SHA-256", credentials,
        )

    command, _, _, _ = make_exchange(
        "SCRAM-SHA-256", credentials, done=False,
    )
    with (
        patch(
            "kover.network.auth.scram.os.urandom",
            return_value=b"client-nonce",
        ),
        pytest.raises(RuntimeError, match="not completed"),
    ):
        await ScramAuthenticator(command).authenticate(
            "SCRAM-SHA-256", credentials,
        )
