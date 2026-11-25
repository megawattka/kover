"""Atomic in-memory topology snapshot storage."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..models.address import Address
    from .description import ServerDescription


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
        self._changed = asyncio.Event()
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
        self.notify()

    @property
    def changed(self) -> asyncio.Event:
        """A signal for the next publication (capture before select)."""
        return self._changed

    def notify(self) -> None:
        """Wake all current waiters without losing concurrent publications."""
        previous, self._changed = self._changed, asyncio.Event()
        previous.set()

    def get(self, address: Address) -> ServerDescription:
        """Return the latest description for an address."""
        return self._descriptions[_address_key(address)]

    def discard(self, address: Address) -> None:
        """Remove a server from the snapshot if it is present."""
        if self._descriptions.pop(_address_key(address), None) is not None:
            self.notify()
