"""AuthCredentials source file."""

from __future__ import annotations

from hashlib import md5
from typing import Any

from pydantic import BaseModel, Field

from ..configuration.environment import (
    read_auth_credentials_from_env,
    resolve_auth_db_from_env,
)


class AuthCredentials(BaseModel):
    """Stores authentication credentials for MongoDB.

    Attributes:
        username : The username for authentication.
        password : The password for authentication.
        auth_database : The database name to authenticate against
            (default is "admin").
    """

    username: str
    password: str = Field(repr=False)
    auth_database: str = Field(default_factory=resolve_auth_db_from_env)

    def md5_hash(self) -> bytes:
        """Returns md5 hashed string for MongoDB. Internal use."""
        hashed = md5(f"{self.username}:mongo:{self.password}".encode())
        return hashed.hexdigest().encode("u8")

    def apply_to(self, document: dict[str, Any]) -> None:
        """Internal use only. Applies auth credentials to hello payload."""
        formatted = f"{self.auth_database}.{self.username}"
        document["saslSupportedMechs"] = formatted

    @classmethod
    def from_environ(cls) -> AuthCredentials | None:
        """Create AuthCredentials from environment variables.

        Reading and validation are delegated to configuration.environment;
        a missing credential pair member propagates CredentialsException.

        Returns:
            AuthCredentials instance if both MONGO_USER and MONGO_PASSWORD
                are set in the environment, otherwise returns None.

        """
        fields = read_auth_credentials_from_env()
        return cls(**fields) if fields is not None else None
