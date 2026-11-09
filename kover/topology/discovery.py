"""Probe seed servers and advertised replica-set members."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from ..exceptions import OperationFailure, PoolTimeoutError, ProtocolError
from ..models.address import Address
from ..models.options import DiscoveryOptions
from ..models.topology import ServerType
from ..network.factory import ConnectionFactory
from ..network.probe import ServerProbe
from ..network.uri_parser import parse_host
from .state import TopologyState

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..models.credentials import AuthCredentials
    from ..models.topology import ServerDescription
    from .protocols import IServerProbe


def _key(address: Address) -> tuple[str, int]:
    return address.host.lower(), address.port


def _parse_address(value: str) -> Address:
    host, port = parse_host(value)
    return Address(host=host, port=port or 27017)


class ServerDiscovery:
    """Discover topology by probing seeds and members via ``hello``."""

    def __init__(
        self,
        seeds: Sequence[Address],
        *,
        options: DiscoveryOptions | None = None,
        probe: IServerProbe | None = None,
        tls: bool = False,
        loop: asyncio.AbstractEventLoop | None = None,
        compression: list[str] | None = None,
        application: dict[str, Any] | None = None,
        credentials: AuthCredentials | None = None,
        state: TopologyState | None = None,
    ) -> None:
        self.options = options or DiscoveryOptions()
        if not seeds:
            raise ValueError("at least one seed is required")

        self._seeds = {_key(seed): seed for seed in seeds}
        # Addresses survive failed probes and empty published snapshots.
        self._known_addresses = dict(self._seeds)
        if self.options.direct_connection and len(self._seeds) != 1:
            raise ValueError("directConnection requires exactly one seed")

        self._tls = tls
        self._loop = loop
        self._compression = compression
        self._application = application
        self._credentials = credentials
        self._probe_adapter = probe or ServerProbe(
            ConnectionFactory(
                tls=tls,
                loop=loop,
                compression=compression,
                application=application,
                credentials=credentials,
            ),
        )
        self._state = state or TopologyState()
        self._set_name = self.options.replica_set
        self._errors: dict[tuple[str, int], str] = {}

    @property
    def direct_connection(self) -> bool:
        """Whether only the configured address may be used."""
        return self.options.direct_connection

    def description(self, address: Address) -> ServerDescription:
        """Return the latest description for an address."""
        return self._state.get(address)

    async def _probe(self, address: Address) -> ServerDescription | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (self.options.connect_timeout or 30.0)
        try:
            return await self._probe_adapter.probe(
                address,
                deadline=deadline,
            )
        except (
            OSError,
            ValueError,
            asyncio.IncompleteReadError,
            OperationFailure,
            PoolTimeoutError,
            ProtocolError,
            TimeoutError,
        ) as e:
            self._errors[_key(address)] = f"{type(e).__name__}: {e}"
            return None

    def _accept(
        self,
        description: ServerDescription,
    ) -> tuple[bool, list[Address]]:
        """Validate a probe and return addresses advertised by its hello.

        Returns:
            A suitability flag and addresses that should be probed next.
        """
        if self.options.direct_connection:
            return self._accept_direct(description)

        if description.hello.set_name is not None:
            return self._accept_replica_member(description)

        return self._accept_non_replica(description)

    def _accept_direct(
        self,
        description: ServerDescription,
    ) -> tuple[bool, list[Address]]:
        hello = description.hello
        address = description.address
        if self._set_name is None or hello.set_name == self._set_name:
            return True, []

        self._errors[_key(address)] = "replica set name does not match"
        return False, []

    def _accept_replica_member(
        self,
        description: ServerDescription,
    ) -> tuple[bool, list[Address]]:
        hello = description.hello
        address = description.address
        if self._set_name is None:
            self._set_name = hello.set_name

        if hello.set_name != self._set_name:
            self._errors[_key(address)] = "replica set name does not match"
            return False, []

        members = [*hello.hosts, *hello.passives, *hello.arbiters]
        parsed = [_parse_address(member) for member in members]
        if not parsed and description.server_type is ServerType.RS_SECONDARY:
            return True, []
        if hello.me is not None and _key(_parse_address(hello.me)) != _key(
            address,
        ):
            return False, [*parsed, _parse_address(hello.me)]

        if description.server_type is ServerType.RS_PRIMARY:
            return self._accept_primary(address, parsed)

        if hello.primary_node:
            parsed.insert(0, _parse_address(hello.primary_node))

        return description.server_type in {
            ServerType.RS_SECONDARY,
            ServerType.RS_ARBITER,
            ServerType.RS_OTHER,
        }, parsed

    def _accept_primary(
        self,
        address: Address,
        members: list[Address],
    ) -> tuple[bool, list[Address]]:
        if members and _key(address) not in {
            _key(member) for member in members
        }:
            self._errors[_key(address)] = "not in primary's member list"
            return False, members

        return True, members

    def _accept_non_replica(
        self,
        description: ServerDescription,
    ) -> tuple[bool, list[Address]]:
        if self._set_name is None:
            if description.server_type is ServerType.MONGOS:
                return True, []
            if (
                description.server_type is ServerType.STANDALONE
                and len(self._seeds) == 1
            ):
                return True, []
        self._errors[_key(description.address)] = (
            f"unsuitable server type: {description.server_type}"
        )
        return False, []

    async def scan(
        self,
        *,
        deadline: float | None = None,
    ) -> tuple[ServerDescription, ...]:
        """Probe reachable topology members and return the complete snapshot.

        Returns:
            All accepted server descriptions, independent of read preference.
        """
        loop = asyncio.get_running_loop()
        scan_deadline = min(
            deadline if deadline is not None else float("inf"),
            loop.time() + self.options.server_selection_timeout,
        )

        self._errors.clear()
        accepted: dict[tuple[str, int], ServerDescription] = {}
        known = dict(self._known_addresses)
        visited: set[tuple[str, int]] = set()
        pending: dict[asyncio.Task[ServerDescription | None], Address] = {}
        try:
            async with asyncio.timeout_at(scan_deadline):
                await self._scan_pending(known, visited, pending, accepted)
        except TimeoutError:
            pass
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        snapshot = tuple(accepted.values())
        self._state.replace(snapshot)
        return snapshot

    async def _scan_pending(
        self,
        known: dict[tuple[str, int], Address],
        visited: set[tuple[str, int]],
        pending: dict[asyncio.Task[ServerDescription | None], Address],
        accepted: dict[tuple[str, int], ServerDescription],
    ) -> None:
        """Probe known addresses and enqueue advertised members."""
        while known or pending:
            self._start_probes(known, visited, pending)
            known.clear()
            if not pending:
                return
            done, _ = await asyncio.wait(
                pending,
                return_when=asyncio.FIRST_COMPLETED,
            )
            self._collect_probes(done, pending, known, accepted)

    def _start_probes(
        self,
        known: dict[tuple[str, int], Address],
        visited: set[tuple[str, int]],
        pending: dict[asyncio.Task[ServerDescription | None], Address],
    ) -> None:
        for key, address in tuple(known.items()):
            if key not in visited:
                visited.add(key)
                task = asyncio.create_task(self._probe(address))
                pending[task] = address

    def _collect_probes(
        self,
        done: set[asyncio.Task[ServerDescription | None]],
        pending: dict[asyncio.Task[ServerDescription | None], Address],
        known: dict[tuple[str, int], Address],
        accepted: dict[tuple[str, int], ServerDescription],
    ) -> None:
        for task in done:
            address = pending.pop(task)
            description = task.result()
            if description is None:
                continue
            suitable, members = self._accept(description)
            if suitable:
                accepted[_key(address)] = description
                self._known_addresses[_key(address)] = address
            discovered = {_key(member): member for member in members}
            self._known_addresses.update(discovered)
            known.update(discovered)
