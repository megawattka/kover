"""The authentication module for MongoDB connections."""

from __future__ import annotations

from base64 import b64decode, b64encode
import hashlib
from hmac import HMAC, compare_digest
import os
from typing import TYPE_CHECKING, Final
from urllib.parse import unquote_plus

from bson import Binary
from pydantic import BaseModel, Field

from ..exceptions import CredentialsException

if TYPE_CHECKING:
    from urllib.parse import ParseResult

    from ..client import MongoTransport
    from ..typings import xJsonT

ITERATIONS: Final[int] = 4096


class AuthCredentials(BaseModel):
    """Stores authentication credentials for MongoDB.

    Attributes:
        username : The username for authentication.
        password : The password for authentication.
        db_name : The database name to authenticate against
            (default is "admin").
    """

    username: str
    password: str = Field(repr=False)
    auth_database: str = Field(default="admin")

    def md5_hash(self) -> bytes:
        """Returns md5 hashed string for MongoDB. Internal use."""
        hashed = hashlib.md5(f"{self.username}:mongo:{self.password}".encode())
        return hashed.hexdigest().encode("u8")

    def apply_to(self, document: xJsonT) -> None:
        """Internal use only. Applies auth credentials to hello payload."""
        formatted = f"{self.auth_database}.{self.username}"
        document["saslSupportedMechs"] = formatted

    @classmethod
    def from_environ(cls) -> AuthCredentials | None:
        """Create AuthCredentials from environment variables.

        Returns:
            AuthCredentials instance if both MONGO_USER and MONGO_PASSWORD
                are set in the environment, otherwise returns None.

        Raises:
            CredentialsException : If only one of MONGO_USER
                or MONGO_PASSWORD is set.
        """
        user, password = os.environ.get("MONGO_USER"), \
            os.environ.get("MONGO_PASSWORD")

        if user is not None and password is not None:
            return cls(username=user, password=password)

        if (user and not password) or (password and not user):
            raise CredentialsException

        return None

    @classmethod
    def from_parts(cls, parts: ParseResult) -> AuthCredentials | None:
        """Return auth credentials based on uri UserInfo."""
        if parts.username is not None and parts.password is not None:
            if len(parts.path) > 1:
                auth_database = unquote_plus(parts.path[1:])
            else:
                auth_database = "admin"
            return cls(
                username=parts.username,
                password=parts.password,
                auth_database=auth_database,
            )
        return None


class Auth:
    """Handles authentication mechanisms for MongoDB connections.

    Attributes:
        transport : The transport used for communication
            with the MongoDB server.
    """

    def __init__(self, transport: MongoTransport) -> None:
        self._transport = transport

    @staticmethod
    def _parse_scram_response(payload: bytes) -> dict[str, bytes]:
        values = [
            item.split(b"=", 1)
            for item in payload.split(b",")
        ]
        return {
            k.decode(): v
            for k, v in values
        }

    @staticmethod
    def xor(fir: bytes, sec: bytes) -> bytes:
        """XOR two byte strings together.

        Returns:
            A bytes object containing the result of the XOR operation.
        """
        return b"".join(
            [bytes([x ^ y]) for x, y in zip(fir, sec, strict=True)],
        )

    @staticmethod
    def _clear_username(username: bytes) -> bytes:
        for x, y in {b"=": b"=3D", b",": b"=2C"}.items():
            username = username.replace(x, y)
        return username

    async def _sasl_start(
        self,
        mechanism: str,
        credentials: AuthCredentials,
    ) -> tuple[bytes, bytes, bytes, int]:
        user = self._clear_username(credentials.username.encode("u8"))
        nonce = b64encode(os.urandom(32))
        first_bare = b"n=" + user + b",r=" + nonce
        command: xJsonT = {
            "saslStart": 1.0,
            "mechanism": mechanism,
            "payload": Binary(b"n,," + first_bare),
            "autoAuthorize": 1,
            "options": {
                "skipEmptyExchange": True,
            },
        }
        request = await self._transport.request(
            doc=command,
            db_name=credentials.auth_database,
        )
        return nonce, request["payload"], first_bare, request["conversationId"]

    async def _sasl_continue(
        self,
        client_final: bytes,
        cid: int,
        credentials: AuthCredentials,
    ) -> xJsonT:
        cmd: xJsonT = {
            "saslContinue": 1.0,
            "conversationId": cid,
            "payload": Binary(client_final),
        }
        request = await self._transport.request(
            cmd, db_name=credentials.auth_database)

        assert request["done"], "SASL conversation not completed."
        return self._parse_scram_response(request["payload"])

    async def create(
        self,
        mechanism: str,
        credentials: AuthCredentials,
    ) -> bytes:
        """Perform SCRAM authentication with the MongoDB server.

        Parameters:
            mechanism : The authentication mechanism to use
                (e.g., "SCRAM-SHA-1", "SCRAM-SHA-256").
            credentials : The authentication credentials containing
                username, password, and database name.

        Returns:
            The server signature after successful authentication.

        Raises:
            ValueError : If an unknown authentication mechanism is provided.
        """
        if mechanism == "SCRAM-SHA-1":
            digest = "sha1"
            digestmod = hashlib.sha1
            data = credentials.md5_hash()
        elif mechanism == "SCRAM-SHA-256":
            digest = "sha256"
            digestmod = hashlib.sha256
            data = credentials.password.encode()
        else:
            raise ValueError("Unknown authentication mechanism.")

        nonce, server_first, first_bare, cid = await self._sasl_start(
            mechanism,
            credentials,
        )
        parsed = self._parse_scram_response(server_first)
        iterations = int(parsed["i"])
        assert iterations > ITERATIONS, "Server sent an wrong iteration count."
        assert parsed["r"].startswith(nonce), "Server sent an invalid nonce."

        salted_pass = hashlib.pbkdf2_hmac(
            digest,
            data,
            b64decode(parsed["s"]),
            iterations,
        )
        keys = (
            HMAC(salted_pass, b"Client Key", digestmod).digest(),
            HMAC(salted_pass, b"Server Key", digestmod).digest(),
        )

        auth_msg = b",".join((
            first_bare,
            server_first,
            b"c=biws,r=" + parsed["r"],
        ))
        client_sig = HMAC(
            digestmod(keys[0]).digest(),  # stored_key
            auth_msg,
            digestmod,
        ).digest()

        client_final = b",".join((
            b"c=biws,r=" + parsed["r"],  # and client_proof
            b"p=" + b64encode(self.xor(keys[0], client_sig)),
        ))
        server_sig = b64encode(
            HMAC(keys[1], auth_msg, digestmod).digest(),
        )
        parsed = await self._sasl_continue(client_final, cid, credentials)
        assert compare_digest(parsed["v"], server_sig)

        return parsed["v"]
