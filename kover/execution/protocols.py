"""Narrow interfaces required by command execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from ..models.address import Address
    from ..models.concerns import WriteConcern
    from ..models.read_preference import ReadPreference
    from ..session import Session


class IServerPool(Protocol):
    """Pool capable of executing a command on one server."""

    async def execute(
        self,
        command: dict[str, Any],
        *,
        database: str,
        deadline: float | None,
    ) -> dict[str, Any]:
        """Execute a prepared command and return its reply."""
        ...

    async def close(self) -> None:
        """Close every server pool."""
        ...


class IPoolProvider(Protocol):
    """Resolve a per-server command pool."""

    def for_server(self, address: Address) -> IServerPool:
        """Return the pool serving ``address``."""
        ...

    async def close(self) -> None:
        """Close pool."""
        ...


class ICommandExecutor(Protocol):
    """Execute a command using selection, preparation, and a server pool."""

    async def execute(
        self,
        command: dict[str, Any],
        *,
        database: str = "admin",
        session: Session | None = None,
        read_preference: ReadPreference | None = None,
        server_address: Address | None = None,
        deadline: float | None = None,
        write_concern: WriteConcern | None = None,
    ) -> dict[str, Any]:
        """Route and execute a command without mutating its input document."""
        ...

    async def close(self) -> None:
        """Release resources owned by this executor."""
        ...
