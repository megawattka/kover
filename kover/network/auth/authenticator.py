"""Authentication mechanism selection and execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .scram import ScramAuthenticator

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ...models.credentials import AuthCredentials
    from ...models.hello import HelloResult


class Authenticator:
    """Select and run the authentication mechanism advertised by hello."""

    def __init__(
        self,
        command: Callable[..., Awaitable[dict[str, Any]]],
    ) -> None:
        self._scram = ScramAuthenticator(command)

    async def authenticate(
        self,
        hello: HelloResult,
        credentials: AuthCredentials | None,
    ) -> bytes | None:
        """Authenticate when the server and client provide credentials.

        Returns:
            The verified server signature, or ``None`` when not applicable.
        """
        if credentials is None:
            return None
        mechanism = hello.get_auth_mechanism()
        if mechanism is None:
            return None
        return await self._scram.authenticate(mechanism, credentials)
