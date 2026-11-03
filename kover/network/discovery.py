"""On-demand server discovery and selection, without monitoring."""

from __future__ import annotations

import asyncio
from collections.abc import Callable  # ruff: ignore[typing-only-standard-library-import]
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
import math
from typing import TYPE_CHECKING

from pymongo.uri_parser import parse_host

from ..exceptions import OperationFailure, ProtocolError, ServerSelectionError
from ..models.network import Address
from ..read_preferences import ReadPreference, validate_threshold
from .selection import candidates, choose

if TYPE_CHECKING:
    from ..models import HelloResult
    from ..typings import DictT
    from .auth import AuthCredentials
    from .connection import Connection


class ServerType(StrEnum):
    """Server roles relevant to initial discovery."""

    STANDALONE = "Standalone"
    MONGOS = "Mongos"
    RS_PRIMARY = "RSPrimary"
    RS_SECONDARY = "RSSecondary"
    RS_ARBITER = "RSArbiter"
    RS_OTHER = "RSOther"
    RS_GHOST = "RSGhost"


@dataclass(frozen=True)
class DiscoveryOptions:
    """Initial selection settings; timeout values are seconds, not ms."""

    replica_set: str | None = None
    direct_connection: bool = False
    server_selection_timeout: float = 30.0
    connect_timeout: float | None = 10.0
    read_preference: ReadPreference = field(default_factory=ReadPreference)
    local_threshold: float = 0.015

    def __post_init__(self) -> None:
        validate_threshold(self.local_threshold)
        if (
            not math.isfinite(self.server_selection_timeout)
            or self.server_selection_timeout < 0
        ):
            raise ValueError(
                "server_selection_timeout must be finite and >= 0",
            )
        if self.connect_timeout is not None and (
            not math.isfinite(self.connect_timeout)
            or self.connect_timeout <= 0
        ):
            raise ValueError("connect_timeout must be finite and > 0, or None")
        if self.replica_set is not None and not self.replica_set:
            raise ValueError("replica_set must not be empty")


@dataclass(frozen=True)
class ServerDescription:
    """An address and its most recently observed hello response."""

    address: Address
    hello: HelloResult
    round_trip_time: float = 0.0
    updated_at: float = 0.0

    @property
    def server_type(self) -> ServerType:
        """Classify the server using SDAM hello role precedence."""
        hello = self.hello
        if hello.msg == "isdbgrid":
            return ServerType.MONGOS
        if hello.is_replica_set:
            return ServerType.RS_GHOST
        if hello.set_name is None:
            return ServerType.STANDALONE
        roles = (
            (hello.hidden, ServerType.RS_OTHER),
            (hello.is_primary, ServerType.RS_PRIMARY),
            (hello.secondary, ServerType.RS_SECONDARY),
            (hello.arbiter_only, ServerType.RS_ARBITER),
        )
        return next(
            (role for matches, role in roles if matches),
            ServerType.RS_OTHER,
        )


def _key(address: Address) -> tuple[str, int]:
    return address.host.lower(), address.port


def _parse_address(value: str) -> Address:
    host, port = parse_host(value)
    return Address(host=host, port=port or 27017)


class ServerDiscovery:
    """Probe seeds and advertised members until a suitable server is found.

    Selection supports direct connections, standalone deployments, replica
    set read preferences and mongos routers, including RTT-based selection.
    It does not implement background monitoring or automatic failover.
    Probes are unauthenticated hello exchanges, never application commands.
    """

    def __init__(
        self,
        seeds: list[Address],
        factory: Callable[[Address], Connection],
        *,
        options: DiscoveryOptions | None = None,
        compression: list[str] | None = None,
        credentials: AuthCredentials | None = None,
        application: DictT | None = None,
    ) -> None:
        self._options = options or DiscoveryOptions()
        if not seeds:
            raise ValueError("at least one seed is required")

        unique = {_key(address): address for address in seeds}
        if self._options.direct_connection and len(unique) != 1:
            raise ValueError("directConnection requires exactly one seed")

        self._seeds = unique
        self._factory = factory
        self._compression = compression
        self._credentials = credentials
        self._application = application
        self._set_name = self._options.replica_set
        self._errors: dict[tuple[str, int], str] = {}
        self._servers: dict[tuple[str, int], ServerDescription] = {}
        self._descriptions: dict[tuple[str, int], ServerDescription] = {}

    def description(self, address: Address) -> ServerDescription:
        """Return the latest verified description for an address."""
        return self._descriptions[_key(address)]

    @property
    def direct_connection(self) -> bool:
        """Whether selection ignores server roles in a single topology."""
        return self._options.direct_connection

    def cached(self, preference: ReadPreference) -> Address | None:
        """Select from the last scan, without network I/O.

        Returns:
            An eligible address, or None when another scan is needed.
        """
        servers = list(self._servers.values())
        if self._options.direct_connection:
            eligible = servers
        else:
            routers = [
                server
                for server in servers
                if server.server_type is ServerType.MONGOS
            ]
            singles = [
                server
                for server in servers
                if server.server_type is ServerType.STANDALONE
            ]
            eligible = routers or singles or candidates(servers, preference)
        selected = choose(eligible, self._options.local_threshold)
        return selected.address if selected is not None else None

    async def _probe(self, address: Address) -> ServerDescription | None:
        connection = self._factory(address)
        try:
            async with asyncio.timeout(self._options.connect_timeout):
                await connection.connect()
                started = asyncio.get_running_loop().time()
                hello = await connection.hello(
                    self._compression,
                    self._credentials,
                    self._application,
                )
            updated = asyncio.get_running_loop().time()
            return ServerDescription(
                address,
                hello,
                updated - started,
                updated,
            )
        except (
            OSError,
            ValueError,
            asyncio.IncompleteReadError,
            OperationFailure,
            ProtocolError,
        ) as error:
            self._errors[_key(address)] = f"{type(error).__name__}: {error}"
            return None
        finally:
            # Invalidate synchronously even if cancellation interrupts close.
            connection.abort()
            with suppress(OSError, TimeoutError):
                async with asyncio.timeout(1.0):
                    await connection.close()

    def _accept_member(
        self,
        description: ServerDescription,
    ) -> tuple[bool, list[Address]]:
        address, hello = description.address, description.hello
        if self._set_name is None:
            self._set_name = hello.set_name

        if hello.set_name != self._set_name:
            self._errors[_key(address)] = "replica set name does not match"
            return False, []

        members = [*(hello.hosts or []), *hello.passives, *hello.arbiters]
        addresses = [_parse_address(member) for member in members]
        if hello.me is not None and _key(_parse_address(hello.me)) != _key(
            address,
        ):
            self._errors[_key(address)] = "hello.me differs from seed address"
            return False, [*addresses, _parse_address(hello.me)]
        if description.server_type is ServerType.RS_PRIMARY:
            if addresses and _key(address) not in {
                _key(member) for member in addresses
            }:
                self._errors[_key(address)] = "not in primary's member list"
                return False, addresses
            return True, addresses
        if hello.primary_node is not None:
            addresses.insert(0, _parse_address(hello.primary_node))
        self._errors[_key(address)] = (
            f"server is {description.server_type}, not primary"
        )
        return description.server_type is ServerType.RS_SECONDARY, addresses

    def _accept(
        self,
        description: ServerDescription,
    ) -> tuple[bool, list[Address]]:
        address, hello = description.address, description.hello
        role = description.server_type
        if self._options.direct_connection:
            if self._set_name is None or hello.set_name == self._set_name:
                return True, []
            self._errors[_key(address)] = "replica set name does not match"
            return False, []

        if hello.set_name is not None:
            return self._accept_member(description)

        if self._set_name is None:
            if role is ServerType.MONGOS:
                return True, []
            if role is ServerType.STANDALONE and len(self._seeds) == 1:
                return True, []
        self._errors[_key(address)] = f"unsuitable server type: {role}"
        return False, []

    def _members(
        self,
        description: ServerDescription,
    ) -> tuple[bool, list[Address]]:
        try:
            return self._accept(description)
        except ValueError as error:
            self._errors[_key(description.address)] = str(error)
            return False, []

    async def _scan(
        self,
        known: dict[tuple[str, int], Address],
        pending: dict[asyncio.Task[ServerDescription | None], Address],
        preference: ReadPreference,
    ) -> Address | None:
        visited: set[tuple[str, int]] = set()
        todo = list(known.values())
        while todo or pending:
            for address in todo:
                key = _key(address)
                if key not in visited:
                    visited.add(key)
                    task = asyncio.create_task(self._probe(address))
                    pending[task] = address
            todo.clear()
            if not pending:
                break
            done, _ = await asyncio.wait(
                pending,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                address = pending.pop(task)
                description = task.result()
                if description is None:
                    continue
                selected, members = self._members(description)
                if selected:
                    self._servers[_key(address)] = description
                    self._descriptions[_key(address)] = description
                    if self._options.direct_connection or (
                        preference.mode in {"primary", "primaryPreferred"}
                        and description.server_type
                        in {
                            ServerType.RS_PRIMARY,
                            ServerType.STANDALONE,
                            ServerType.MONGOS,
                        }
                    ):
                        return address
                for member in members:
                    known[_key(member)] = member
                todo.extend(members)
        return self.cached(preference)

    async def _select(
        self,
        pending: dict[asyncio.Task[ServerDescription | None], Address],
        deadline: float,
        preference: ReadPreference,
    ) -> Address:
        known = self._seeds.copy()
        while True:
            self._servers.clear()
            selected = await self._scan(known, pending, preference)
            if selected is not None:
                return selected
            remaining = deadline - asyncio.get_running_loop().time()
            await asyncio.sleep(min(0.5, max(0, remaining)))

    async def select(
        self,
        preference: ReadPreference | None = None,
        *,
        deadline: float | None = None,
    ) -> Address:
        """Discover and return a verified suitable address.

        Returns:
            The address whose own hello satisfies the topology constraints.

        Raises:
            ServerSelectionError: If no suitable server is found in time.
        """
        pending: dict[asyncio.Task[ServerDescription | None], Address] = {}
        preference = preference or self._options.read_preference
        loop = asyncio.get_running_loop()
        selection_deadline = (
            loop.time() + self._options.server_selection_timeout
        )
        if deadline is not None:
            selection_deadline = min(selection_deadline, deadline)
        try:
            async with asyncio.timeout_at(selection_deadline):
                return await self._select(
                    pending,
                    selection_deadline,
                    preference,
                )
        except TimeoutError as error:
            selected = self.cached(preference)
            if selected is not None:
                return selected
            details = "; ".join(
                f"{host}:{port}: {reason}"
                for (host, port), reason in self._errors.items()
            )
            raise ServerSelectionError(
                f"No suitable server found (replicaSet={self._set_name!r}, "
                f"seeds={list(self._seeds)}). {details}",
            ) from error
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
