"""Snapshot-based server selection for the v2 driver architecture."""

from __future__ import annotations

import asyncio
from secrets import choice
from typing import TYPE_CHECKING

from ..exceptions import ServerSelectionError
from .description import ServerType
from .protocols import IServerSelector
from .state import TopologyState

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..models.address import Address
    from ..models.read_preference import ReadPreference
    from .description import ServerDescription
    from .monitor import TopologyMonitor
    from .options import DiscoveryOptions
    from .protocols import IServerDiscovery


def _tag_matches(
    server: ServerDescription,
    tag_set: dict[str, str],
) -> bool:
    return all(server.tags.get(key) == value for key, value in tag_set.items())


def _last_write(server: ServerDescription) -> float | None:
    value = server.last_write_date
    if value is None:
        return None

    return value.timestamp()


def _fresh_secondaries(
    secondaries: list[ServerDescription],
    primary: ServerDescription | None,
    maximum_staleness: int,
    heartbeat_frequency: float,
) -> list[ServerDescription]:
    if maximum_staleness == -1:
        return secondaries

    secondary_writes = [_last_write(server) for server in secondaries]
    primary_write = _last_write(primary) if primary is not None else None
    if primary is not None and primary_write is None:
        return []

    newest_secondary_write = max(
        (write for write in secondary_writes if write is not None),
        default=0.0,
    )
    fresh: list[ServerDescription] = []

    for secondary, secondary_write in zip(
        secondaries,
        secondary_writes,
        strict=True,
    ):
        if secondary_write is None:
            continue

        if primary is not None and primary_write is not None:
            staleness = (
                secondary.updated_at
                - primary.updated_at
                + primary_write
                - secondary_write
                + heartbeat_frequency
            )
        else:
            staleness = (
                newest_secondary_write - secondary_write + heartbeat_frequency
            )

        if staleness <= maximum_staleness:
            fresh.append(secondary)

    return fresh


def _by_tags(
    servers: list[ServerDescription],
    preference: ReadPreference,
) -> list[ServerDescription]:
    for tag_set in preference.tag_sets or ({},):
        matches = [
            server for server in servers if _tag_matches(server, dict(tag_set))
        ]
        if matches:
            return matches
    return []


def eligible_servers(
    servers: Iterable[ServerDescription],
    preference: ReadPreference,
    *,
    heartbeat_frequency: float = 10.0,
) -> list[ServerDescription]:
    """Filter a topology snapshot using MongoDB read preference rules.

    Returns:
        list of ServerDescription.
    """
    members = list(servers)
    primary = next(
        (
            server
            for server in members
            if server.server_type is ServerType.RS_PRIMARY
        ),
        None,
    )
    primaries = [primary] if primary is not None else []

    if preference.mode == "primary":
        return primaries

    if preference.mode == "primaryPreferred" and primary is not None:
        return primaries

    secondaries = _fresh_secondaries(
        [
            server
            for server in members
            if server.server_type is ServerType.RS_SECONDARY
        ],
        primary,
        preference.max_staleness_seconds,
        heartbeat_frequency,
    )

    if preference.mode == "nearest":
        return _by_tags([*primaries, *secondaries], preference)

    matched_secondaries = _by_tags(secondaries, preference)
    if preference.mode == "secondaryPreferred" and not matched_secondaries:
        return primaries

    return matched_secondaries


def _latency_candidates(
    servers: list[ServerDescription],
    local_threshold: float,
) -> list[ServerDescription]:
    if not servers:
        return []

    fastest = min(server.round_trip_time for server in servers)
    return [
        server
        for server in servers
        if server.round_trip_time <= fastest + local_threshold
    ]


class ServerSelector(IServerSelector):
    """Select eligible servers from a snapshot, refreshing it on demand."""

    def __init__(
        self,
        discovery: IServerDiscovery | None,
        options: DiscoveryOptions,
        initial_descriptions: Iterable[ServerDescription] = (),
        state: TopologyState | None = None,
        *,
        monitor: TopologyMonitor | None = None,
    ) -> None:
        self._discovery = discovery
        self._options = options
        self._monitor = monitor
        self._state = (
            monitor.state
            if monitor is not None
            else (state or TopologyState(initial_descriptions))
        )
        self._lock = asyncio.Lock()

    @property
    def direct_connection(self) -> bool:
        """Whether all operations must use the sole configured address."""
        return self._options.direct_connection

    @property
    def descriptions(self) -> tuple[ServerDescription, ...]:
        """Latest known server descriptions, for policy evaluation."""
        return self._state.descriptions

    def replace_descriptions(
        self,
        descriptions: Iterable[ServerDescription],
    ) -> None:
        """Atomically publish fresh server descriptions."""
        self._state.replace(descriptions)

    def invalidate(self, address: Address) -> None:
        """Remove a stale or failed server from the selectable snapshot."""
        self._state.discard(address)

    def description(self, address: Address) -> ServerDescription:
        """Return the most recently observed description for an address.

        Returns:
            Description for address.

        Raises:
            ServerSelectionError: if description cannot be retrieved.
        """
        try:
            return self._state.get(address)
        except KeyError as exc:
            msg = f"srv {address.host}:{address.port} has no known description"
            raise ServerSelectionError(
                msg,
            ) from exc

    async def select(
        self,
        preference: ReadPreference,
        *,
        deadline: float | None = None,
    ) -> Address:
        """Choose a server from cache or refresh discovery until deadline.

        Discovery is the I/O boundary: it must return a complete selection
        snapshot, not mutate this selector's mapping while a scan is active.

        Returns:
            address of selected server.

        Raises:
            ServerSelectionError: if description cannot be retrieved.
        """
        preference = preference or self._options.read_preference
        if self._monitor is not None:
            return await self._select_monitored(preference, deadline)
        if self._options.direct_connection:
            return await self._select_direct(
                deadline=deadline,
            )

        selected = self._choose(preference)
        if selected is not None:
            return selected.address

        selection_deadline = (
            asyncio.get_running_loop().time()
            + self._options.server_selection_timeout
        )
        if deadline is not None:
            selection_deadline = min(selection_deadline, deadline)

        try:
            async with asyncio.timeout_at(selection_deadline), self._lock:
                selected = self._choose(preference)
                if selected is not None:
                    return selected.address
                return await self._select_until_deadline(
                    preference,
                    selection_deadline,
                )
        except TimeoutError as exc:
            msg = "server selection deadline expired"
            raise ServerSelectionError(
                msg,
            ) from exc

    async def _select_monitored(
        self,
        preference: ReadPreference,
        deadline: float | None,
    ) -> Address:
        monitor = self._monitor
        assert monitor is not None
        limit = (
            asyncio.get_running_loop().time()
            + self._options.server_selection_timeout
        )
        if deadline is not None:
            limit = min(limit, deadline)
        monitor.start()
        try:
            async with asyncio.timeout_at(limit):
                return await self._wait_for_server(monitor, preference)
        except TimeoutError as exc:
            errors = "; ".join(
                f"{s.address.host}:{s.address.port}: "
                f"{s.last_error or s.server_type}"
                for s in self.descriptions
            )
            msg = (
                f"server selection deadline expired ({monitor.kind}): {errors}"
            )
            raise ServerSelectionError(msg) from exc

    async def _wait_for_server(
        self,
        monitor: TopologyMonitor,
        preference: ReadPreference,
    ) -> Address:
        while not monitor.closed:
            changed = self._state.changed
            selected = self._choose(preference)
            if selected is not None:
                return selected.address
            monitor.request_refresh()
            await changed.wait()
        msg = "topology monitor is closed"
        raise ServerSelectionError(msg)

    async def _select_direct(
        self,
        *,
        deadline: float | None,
    ) -> Address:
        """Select the configured direct server regardless of its current role.

        Returns:
            Address: The address of the direct server.

        Raises:
            ServerSelectionError: If no server discovered before the deadline.
        """
        if self.descriptions:
            return self.descriptions[0].address

        selection_deadline = (
            asyncio.get_running_loop().time()
            + self._options.server_selection_timeout
        )
        if deadline is not None:
            selection_deadline = min(selection_deadline, deadline)

        try:  # ruff: ignore[too-many-statements-in-try-clause]
            async with asyncio.timeout_at(selection_deadline), self._lock:
                if not self.descriptions:
                    assert self._discovery is not None
                    refreshed = await self._discovery.scan(
                        deadline=selection_deadline,
                    )
                    self.replace_descriptions(refreshed)

                if not self.descriptions:
                    msg = "no server discovered for direct connection"
                    raise ServerSelectionError(
                        msg,
                    )

                return self.descriptions[0].address
        except TimeoutError as exc:
            msg = (
                "no server found for direct connection "
                "before the selection deadline"
            )
            raise ServerSelectionError(
                msg,
            ) from exc

    async def _select_until_deadline(
        self,
        preference: ReadPreference,
        deadline: float,
    ) -> Address:
        """Refresh discovery until a candidate appears or selection expires.

        Returns:
            Selected server address.

        Raises:
            TimeoutError: if deadline occur.
        """
        loop = asyncio.get_running_loop()
        assert self._discovery is not None
        while True:
            refreshed = await self._discovery.scan(
                deadline=deadline,
            )
            self.replace_descriptions(refreshed)
            selected = self._choose(preference)
            if selected is not None:
                return selected.address

            remaining = deadline - loop.time()
            if remaining <= 0:
                msg = "server selection deadline expired"
                raise TimeoutError(msg)
            await asyncio.sleep(min(0.5, remaining))

    def _choose(
        self,
        preference: ReadPreference,
    ) -> ServerDescription | None:
        descriptions = self.descriptions
        if self.direct_connection:
            return next(
                (
                    s
                    for s in descriptions
                    if s.server_type is not ServerType.UNKNOWN
                ),
                None,
            )

        routers = [
            server
            for server in descriptions
            if server.server_type is ServerType.MONGOS
        ]
        if routers:
            eligible = routers
        else:
            standalone = [
                server
                for server in descriptions
                if server.server_type is ServerType.STANDALONE
            ]
            eligible = standalone or eligible_servers(
                descriptions,
                preference,
                heartbeat_frequency=self._options.heartbeat_frequency,
            )

        latency_window = _latency_candidates(
            eligible,
            self._options.local_threshold,
        )
        return choice(latency_window) if latency_window else None
