"""Shared SCRAM-SHA-1 and SCRAM-SHA-256 implementation."""

from __future__ import annotations

from base64 import b64decode, b64encode
import hashlib
from hmac import HMAC, compare_digest
import os
from typing import TYPE_CHECKING, Any

from bson import Binary

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ...models.credentials import AuthCredentials


MIN_ITERATIONS = 4096


def _parse_attributes(payload: bytes) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for item in payload.split(b","):
        key, separator, value = item.partition(b"=")
        if not separator or not key:
            raise ValueError("invalid SCRAM server response")
        result[key.decode("ascii")] = value
    return result


def _escape_username(username: bytes) -> bytes:
    return username.replace(b"=", b"=3D").replace(b",", b"=2C")


def _xor(first: bytes, second: bytes) -> bytes:
    if len(first) != len(second):
        raise ValueError("SCRAM values must have the same length")
    return bytes(a ^ b for a, b in zip(first, second, strict=True))


class ScramAuthenticator:
    """Run one SCRAM conversation through a command callback."""

    def __init__(
        self,
        command: Callable[..., Awaitable[dict[str, Any]]],
    ) -> None:
        self._command = command

    async def authenticate(  # ruff: ignore[too-many-locals]
        self,
        mechanism: str,
        credentials: AuthCredentials,
    ) -> bytes:
        """Authenticate and return the verified server signature.

        Returns:
            The verified server signature.

        Raises:
            RuntimeError: If the server does not complete the conversation.
            ValueError: If the mechanism or server proof is invalid.
        """
        if mechanism == "SCRAM-SHA-1":
            digest_name, digestmod = "sha1", hashlib.sha1
            password = credentials.md5_hash()

        elif mechanism == "SCRAM-SHA-256":
            digest_name, digestmod = "sha256", hashlib.sha256
            password = credentials.password.encode()
        else:
            raise ValueError(
                f"unsupported authentication mechanism: {mechanism}",
            )

        nonce = b64encode(os.urandom(32))
        first_bare = b"n=" + _escape_username(credentials.username.encode())
        first_bare += b",r=" + nonce
        start = await self._command(
            {
                "saslStart": 1.0,
                "mechanism": mechanism,
                "payload": Binary(b"n,," + first_bare),
                "autoAuthorize": 1,
                "options": {"skipEmptyExchange": True},
            },
            database=credentials.auth_database,
        )
        server_first = bytes(start["payload"])
        fields = _parse_attributes(server_first)
        iterations = int(fields["i"])
        if iterations < MIN_ITERATIONS:
            raise ValueError("server sent an invalid iteration count")

        server_nonce = fields["r"]
        if not server_nonce.startswith(nonce):
            raise ValueError("server sent an invalid nonce")

        salted = hashlib.pbkdf2_hmac(
            digest_name,
            password,
            b64decode(fields["s"]),
            iterations,
        )
        client_key = HMAC(salted, b"Client Key", digestmod).digest()
        server_key = HMAC(salted, b"Server Key", digestmod).digest()
        final_without_proof = b"c=biws,r=" + server_nonce
        auth_message = b",".join(
            (first_bare, server_first, final_without_proof),
        )
        client_signature = HMAC(
            digestmod(client_key).digest(),
            auth_message,
            digestmod,
        ).digest()

        proof = b64encode(_xor(client_key, client_signature))
        server_signature = b64encode(
            HMAC(server_key, auth_message, digestmod).digest(),
        )
        final = await self._command(
            {
                "saslContinue": 1.0,
                "conversationId": start["conversationId"],
                "payload": Binary(final_without_proof + b",p=" + proof),
            },
            database=credentials.auth_database,
        )
        if not final.get("done"):
            raise RuntimeError("SASL conversation not completed")

        response = _parse_attributes(bytes(final["payload"]))
        if not compare_digest(response.get("v", b""), server_signature):
            raise ValueError("authentication failed: server signatures differ")

        return server_signature
