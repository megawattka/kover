"""One-shot discovery for callers that do not own a background monitor."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar

from ..exceptions import OperationFailure, PoolTimeoutError, ProtocolError
from ..network.factory import ConnectionFactory
from ..topology.probe import ServerProbe
from .description import ServerDescription, ServerType  # ruff: ignore[typing-only-first-party-import]
from .options import DiscoveryOptions
from .sdam import Topology
from .state import TopologyState

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..models.address import Address
    from ..models.credentials import AuthCredentials
    from .protocols import IServerProbe


class ServerDiscovery:
    """Discover topology with bounded, serialized on-demand scans."""

    _MAX_CONCURRENT_PROBES: ClassVar[int] = 10

    def __init__(  # ruff: ignore[too-many-arguments] -- Explicit discovery configuration and injectable components.
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
        self._topology = Topology(seeds, self.options)
        self._state = state or TopologyState()
        self._state.replace(self._topology.servers.values())
        self._lock = asyncio.Lock()
        self._probe_adapter = probe or ServerProbe(
            ConnectionFactory(
                tls=tls,
                loop=loop,
                compression=compression,
                application=application,
                credentials=credentials,
            ),
        )

    @property
    def direct_connection(self) -> bool:
        """Whether only the configured address may be used."""
        return self.options.direct_connection

    def description(self, address: Address) -> ServerDescription:
        """Return the latest description, including unavailable addresses."""
        return self._state.get(address)

    async def scan(
        self,
        *,
        deadline: float | None = None,
    ) -> tuple[ServerDescription, ...]:
        """Return the reachable members while retaining failures in state."""
        scan_deadline = (
            asyncio.get_running_loop().time()
            + self.options.server_selection_timeout
        )
        if deadline is not None:
            scan_deadline = min(deadline, scan_deadline)
        try:
            async with asyncio.timeout_at(scan_deadline), self._lock:
                await self._scan()
        except TimeoutError:
            pass
        return tuple(
            s
            for s in self._state.descriptions
            if s.server_type is not ServerType.UNKNOWN
        )

    async def _scan(self) -> None:
        pending: dict[asyncio.Task[ServerDescription], tuple[str, int]] = {}
        visited: set[tuple[str, int]] = set()
        try:
            while True:
                for key, server in self._topology.servers.items():
                    if len(pending) >= self._MAX_CONCURRENT_PROBES:
                        break
                    if key not in visited:
                        visited.add(key)
                        pending[asyncio.create_task(self._probe(server))] = key
                if not pending:
                    return
                done, _ = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    del pending[task]
                    self._topology.update(task.result())
                self._state.replace(self._topology.servers.values())
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    async def _probe(self, server: ServerDescription) -> ServerDescription:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (self.options.connect_timeout or 10.0)
        try:
            async with asyncio.timeout_at(deadline):
                return await self._probe_adapter.probe(
                    server.address,
                    deadline=deadline,
                )
        except (
            OSError,
            ValueError,
            asyncio.IncompleteReadError,
            OperationFailure,
            PoolTimeoutError,
            ProtocolError,
        ) as exc:
            return Topology.unavailable(
                server,
                f"{type(exc).__name__}: {exc}",
            ).model_copy(update={"updated_at": loop.time()})
