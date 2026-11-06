"""Contracts between topology selection and discovery I/O."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..models.address import Address
    from ..models.read_preference import ReadPreference
    from ..models.topology import ServerDescription


class IServerDiscovery(Protocol):
    """Probe servers and return a complete topology snapshot."""

    async def scan(
        self,
        *,
        deadline: float | None = None,
    ) -> Sequence[ServerDescription]:
        """Return descriptions observed during one scan."""
        ...


class IServerProbe(Protocol):
    """Open and handshake one server for topology discovery."""

    async def probe(
        self,
        address: Address,
        *,
        deadline: float | None = None,
    ) -> ServerDescription:
        """Return the description observed at ``address``."""
        ...


class IServerSelector(Protocol):
    """Select an address from the current topology snapshot."""

    @property
    def direct_connection(self) -> bool:
        """True if conn is direct False otherwise."""
        ...

    def description(self, address: Address) -> ServerDescription:
        """Return the latest known description for an address."""
        ...

    def invalidate(self, address: Address) -> None:
        """Forget the cached description for a server that failed an operation."""  # ruff: ignore[line-too-long]
        ...

    async def select(
        self,
        preference: ReadPreference,
        *,
        deadline: float | None = None,
    ) -> Address:
        """Select an address before the deadline."""
        ...
