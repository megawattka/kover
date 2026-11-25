"""Background SDAM monitoring over connections separate from command pools."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ..configuration.environment import is_faas
from ..exceptions import OperationFailure, ProtocolError
from ..network.hello import TopologyVersion
from .description import ServerDescription, ServerType
from .options import MIN_HEARTBEAT_INTERVAL
from .sdam import Topology
from .state import TopologyState

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ..models.address import Address
    from ..network.connection import Connection
    from ..network.factory import ConnectionFactory
    from ..network.hello import HelloResult
    from .description import TopologyType
    from .options import DiscoveryOptions


def _key(address: Address) -> tuple[str, int]:
    return address.host.lower(), address.port


logger = logging.getLogger(__name__)
_CHECK_ERRORS = (OSError, ValueError, ProtocolError, OperationFailure)
_SHUTDOWN_CODES = {91, 11600}
_POOL_CLEAR_WIRE_VERSION = 8


class TopologyMonitor:
    """Own one cancellable heartbeat loop per current server address."""

    def __init__(
        self,
        seeds: Sequence[Address],
        options: DiscoveryOptions,
        factory: ConnectionFactory,
        *,
        clear_pool: Callable[[Address], None],
        initial_descriptions: Sequence[ServerDescription] = (),
    ) -> None:
        self._topology = Topology(seeds, options)
        for description in initial_descriptions:
            self._topology.servers.setdefault(
                _key(description.address),
                description,
            )
        self.state = TopologyState(self._topology.servers.values())
        self._factory = factory
        self._clear_pool = clear_pool
        self._workers: dict[tuple[str, int], _ServerMonitor] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._connections = asyncio.Semaphore(10)
        self.interval = options.heartbeat_frequency
        self.timeout = options.connect_timeout or 10.0
        self.streaming = options.server_monitoring_mode == "stream" or (
            options.server_monitoring_mode == "auto" and not is_faas()
        )
        self.closed = False

    @property
    def kind(self) -> TopologyType:
        """Current topology classification."""
        return self._topology.kind

    def start(self) -> None:
        """Start monitoring on the current loop, once per address."""
        if not self.closed:
            self._reconcile()

    async def stop(self) -> None:
        """Cancel and join all tasks, including workers recently removed."""
        if not self.closed:
            self.closed = True
            self.state.notify()
            for worker in self._workers.values():
                worker.task.cancel()
            self._workers.clear()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def request_refresh(self) -> None:
        """Expedite polling checks without interrupting healthy streams."""
        for worker in self._workers.values():
            worker.request_check()

    async def connect(self, address: Address) -> Connection:
        """Bound parallel handshakes without serializing awaitable hellos.

        Returns:
            An initialized monitoring connection.
        """
        async with self._connections:
            return await self._factory.create_monitor(
                address,
                deadline=asyncio.get_running_loop().time() + self.timeout,
            )

    def publish(
        self,
        worker: _ServerMonitor,
        description: ServerDescription,
    ) -> bool:
        """Publish a heartbeat only if its worker still owns the address.

        Returns:
            Whether the worker remains active after publication.
        """
        if self._workers.get(_key(worker.address)) is not worker:
            return False
        before = self.state.descriptions
        previous_kind = self.kind
        if self._topology.update(description):
            self._publish(before, previous_kind)
        return self._workers.get(_key(worker.address)) is worker

    def application_error(self, address: Address, error: Exception) -> None:
        """Invalidate a server after an applicable command or network error."""
        key = _key(address)
        previous = self._topology.servers.get(key)
        if self.closed or previous is None:
            return

        hello = previous.hello
        clear_pool = True
        if isinstance(error, OperationFailure):
            if not error.is_server_selection_error:
                return
            try:
                version = TopologyVersion.model_validate(
                    error.details.get("topologyVersion"),
                )
            except ValidationError:
                version = None
            if version is not None:
                if version.compare(hello.topology_version) <= 0:
                    return
                hello = hello.model_copy(update={"topology_version": version})
            clear_pool = (
                hello.max_wire_version or 0
            ) < _POOL_CLEAR_WIRE_VERSION or error.code in _SHUTDOWN_CODES

        if clear_pool:
            self._clear_pool(address)
        self._mark_unknown(previous.model_copy(update={"hello": hello}), error)
        if worker := self._workers.get(key):
            worker.request_check(interrupt=True)
        self.request_refresh()

    def heartbeat_error(
        self,
        worker: _ServerMonitor,
        error: Exception,
    ) -> None:
        """Mark the failed addr unknown without removing it from monitoring."""
        key = _key(worker.address)
        if self._workers.get(key) is worker:
            self._clear_pool(worker.address)
            self._mark_unknown(self._topology.servers[key], error)

    def _mark_unknown(
        self,
        previous: ServerDescription,
        error: Exception,
    ) -> None:
        before = self.state.descriptions
        previous_kind = self.kind
        description = Topology.unavailable(
            previous,
            f"{type(error).__name__}: {error}",
        )
        self._topology.update(
            description.model_copy(
                update={
                    "updated_at": asyncio.get_running_loop().time(),
                },
            ),
        )
        self._publish(before, previous_kind)

    def _publish(
        self,
        before: tuple[ServerDescription, ...],
        previous_kind: TopologyType,
    ) -> None:
        after = tuple(self._topology.servers.values())
        self.state.replace(after)
        old_roles = {_key(s.address): s.server_type for s in before}
        new_roles = {_key(s.address): s.server_type for s in after}
        if old_roles != new_roles or self.kind is not previous_kind:
            logger.debug(
                "Topology changed: %s %s -> %s %s",
                previous_kind,
                old_roles,
                self.kind,
                new_roles,
            )
        self._reconcile()
        for key, worker in self._workers.items():
            if (
                old_roles.get(key) is ServerType.RS_PRIMARY
                and new_roles[key] is ServerType.UNKNOWN
                and worker.task is not asyncio.current_task()
            ):
                worker.request_check(interrupt=True)

    def _reconcile(self) -> None:
        for key in self._workers.keys() - self._topology.servers.keys():
            worker = self._workers.pop(key)
            if worker.task is not asyncio.current_task():
                worker.task.cancel()
            self._clear_pool(worker.address)
        for key, server in self._topology.servers.items():
            if key not in self._workers:
                worker = _ServerMonitor(self, server.address)
                self._workers[key] = worker
                self._tasks.add(worker.task)
                worker.task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("Topology monitor failed", exc_info=error)


class _ServerMonitor:
    def __init__(self, topology: TopologyMonitor, address: Address) -> None:
        self.address = address
        self._topology = topology
        self._wake = asyncio.Event()
        self._check: asyncio.Task[HelloResult] | None = None
        self._reset = False
        self._rtt: float | None = None
        self.task = asyncio.create_task(
            self._run(),
            name=f"kover-monitor-{address}",
        )

    def request_check(self, *, interrupt: bool = False) -> None:
        self._wake.set()
        if interrupt:
            self._reset = True
            if self._check is not None:
                self._check.cancel()

    def _sample(self, rtt: float) -> None:
        self._rtt = rtt if self._rtt is None else 0.8 * self._rtt + 0.2 * rtt

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        failures = 0
        while True:
            self._reset = False
            started = loop.time()
            try:
                if not await self._connected():
                    return
                failures = 0
            except _CHECK_ERRORS as exc:
                self._topology.heartbeat_error(self, exc)
                failures = 1 if self._rtt is not None else failures + 1
                self._rtt = None
            # Retry once quickly on disconnect, then exponentially back off.
            if failures:
                delay = min(
                    self._topology.interval,
                    MIN_HEARTBEAT_INTERVAL * 2 ** min(failures - 1, 20),
                )
                await self._wait(started, delay)

    async def _connected(self) -> bool:
        connection = await self._topology.connect(self.address)
        rtt_task: asyncio.Task[None] | None = None
        try:
            hello = connection.hello_result
            if hello is None:
                msg = "monitor connection did not complete hello"
                raise ProtocolError(msg)
            self._sample(connection.hello_round_trip_time)
            while not self._reset:
                started = asyncio.get_running_loop().time()
                if not self._topology.publish(
                    self,
                    ServerDescription(
                        address=self.address,
                        hello=hello,
                        updated_at=started,
                        round_trip_time=self._rtt or 0.0,
                    ),
                ):
                    return False
                version = (
                    hello.topology_version
                    if self._topology.streaming
                    else None
                )
                if version is None:
                    await self._wait(started, self._topology.interval)
                elif rtt_task is None:
                    rtt_task = asyncio.create_task(self._measure_rtt())
                if self._reset:
                    break
                result = await self._heartbeat(connection, version)
                if result is None:
                    break
                hello = result
            return True
        finally:
            if rtt_task is not None:
                rtt_task.cancel()
            try:
                await self._close(connection)
            finally:
                if rtt_task is not None:
                    await asyncio.gather(rtt_task, return_exceptions=True)

    async def _heartbeat(
        self,
        connection: Connection,
        version: TopologyVersion | None,
    ) -> HelloResult | None:
        loop = asyncio.get_running_loop()
        started = loop.time()
        interval = self._topology.interval if version is not None else 0.0
        self._check = asyncio.create_task(
            connection.monitor_hello(
                deadline=started + self._topology.timeout + interval,
                topology_version=version,
                max_await_time_ms=int(interval * 1000),
            ),
        )
        try:
            hello = await self._check
        except asyncio.CancelledError:
            if self._reset and not self.task.cancelling():
                return None
            raise
        finally:
            self._check = None
        if version is None:
            self._sample(loop.time() - started)
        return hello

    async def _measure_rtt(self) -> None:
        while True:
            connection = None
            try:
                await asyncio.sleep(self._topology.interval)
                connection = await self._topology.connect(self.address)
                await self._sample_connection(connection)
            except _CHECK_ERRORS:
                # A latency sample is not an authoritative heartbeat.
                pass
            finally:
                if connection is not None:
                    await self._close(connection)

    async def _sample_connection(self, connection: Connection) -> None:
        loop = asyncio.get_running_loop()
        self._sample(connection.hello_round_trip_time)
        while True:
            await asyncio.sleep(self._topology.interval)
            started = loop.time()
            await connection.monitor_hello(
                deadline=started + self._topology.timeout,
            )
            self._sample(loop.time() - started)

    async def _wait(self, started: float, interval: float) -> None:
        loop = asyncio.get_running_loop()
        with suppress(TimeoutError):
            async with asyncio.timeout_at(started + interval):
                await self._wake.wait()
        await asyncio.sleep(
            max(0.0, started + MIN_HEARTBEAT_INTERVAL - loop.time()),
        )
        self._wake.clear()

    @staticmethod
    async def _close(connection: Connection) -> None:
        with suppress(OSError):
            await connection.close()
