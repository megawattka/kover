"""The authentication module for MongoDB connections."""

from __future__ import annotations

from base64 import b64decode, b64encode
import hashlib
from hmac import HMAC, compare_digest
import os
from typing import TYPE_CHECKING, Final

from bson import Binary
from pydantic import BaseModel, Field

from ..exceptions import CredentialsException
from ..helpers import resolve_auth_db_from_env

if TYPE_CHECKING:
    from ..network.connection import Connection
    from ..typings import DictT

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
    auth_database: str = Field(default_factory=resolve_auth_db_from_env)

    def md5_hash(self) -> bytes:
        """Returns md5 hashed string for MongoDB. Internal use."""
        hashed = hashlib.md5(f"{self.username}:mongo:{self.password}".encode())
        return hashed.hexdigest().encode("u8")

    def apply_to(self, document: DictT) -> None:
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
        user = os.environ.get("MONGO_USER")
        password = os.environ.get("MONGO_PASSWORD")

        if user is not None and password is not None:
            return cls(username=user, password=password)

        if (user and not password) or (password and not user):
            raise CredentialsException

        return None


class Auth:
    """Handles authentication mechanisms for MongoDB connections.

    Attributes:
        transport : The transport used for communication
            with the MongoDB server.
    """

    def __init__(self, transport: Connection) -> None:
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
        command: DictT = {
            "saslStart": 1.0,
            "mechanism": mechanism,
            "payload": Binary(b"n,," + first_bare),
            "autoAuthorize": 1,
            "options": {
                "skipEmptyExchange": True,
            },
        }
        request = await self._transport.command(
            document=command,
            database=credentials.auth_database,
        )
        return nonce, request["payload"], first_bare, request["conversationId"]

    async def _sasl_continue(
        self,
        client_final: bytes,
        cid: int,
        credentials: AuthCredentials,
    ) -> DictT:
        cmd: DictT = {
            "saslContinue": 1.0,
            "conversationId": cid,
            "payload": Binary(client_final),
        }
        request = await self._transport.command(
            cmd, database=credentials.auth_database)

        if not request.get("done"):
            raise RuntimeError("SASL conversation not completed.")

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

        if iterations <= ITERATIONS:
            raise ValueError("Server sent an wrong iteration count.")

        if not parsed["r"].startswith(nonce):
            raise ValueError("Server sent an invalid nonce.")

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

        if not compare_digest(parsed["v"], server_sig):
            raise ValueError("Auth failed. Digests are different.")

        return parsed["v"]
