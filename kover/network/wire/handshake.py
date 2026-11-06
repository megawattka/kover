"""MongoDB hello handshake."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...models.hello import HelloResult

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ...models.credentials import AuthCredentials


class Handshake:
    """Build hello and validate the server capabilities response."""

    def __init__(
        self,
        command: Callable[..., Awaitable[dict[str, Any]]],
    ) -> None:
        self._command = command

    async def hello(
        self,
        payload: dict[str, Any],
        credentials: AuthCredentials | None = None,
    ) -> HelloResult:
        """Send hello and return its validated response.

        Returns:
            Validated server capabilities.
        """
        document = dict(payload)
        if credentials is not None:
            credentials.apply_to(document)

        return HelloResult.model_validate(await self._command(document))
