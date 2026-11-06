"""Atomic in-memory topology snapshot storage."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..models.address import Address
    from ..models.topology import ServerDescription


def _address_key(address: Address) -> tuple[str, int]:
    return address.host.lower(), address.port


class TopologyState:
    """Store and publish the latest server descriptions as one snapshot."""

    def __init__(
        self,
        descriptions: Iterable[ServerDescription] = (),
    ) -> None:
        self._descriptions: dict[
            tuple[str, int],
            ServerDescription,
        ] = {}
        self.replace(descriptions)

    @property
    def descriptions(self) -> tuple[ServerDescription, ...]:
        """Current immutable snapshot."""
        return tuple(self._descriptions.values())

    def replace(self, descriptions: Iterable[ServerDescription]) -> None:
        """Atomically replace the current snapshot."""
        self._descriptions = {
            _address_key(description.address): description
            for description in descriptions
        }

    def get(self, address: Address) -> ServerDescription:
        """Return the latest description for an address."""
        return self._descriptions[_address_key(address)]

    def discard(self, address: Address) -> None:
        """Remove a server from the snapshot if it is present."""
        self._descriptions.pop(_address_key(address), None)
