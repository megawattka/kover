"""Network adapter implementing the topology server-probe contract."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ..models.topology import ServerDescription

if TYPE_CHECKING:
    from ..models.address import Address
    from ..models.hello import HelloResult
    from .factory import ConnectionFactory


class ServerProbe:
    """Probe one server using a short-lived initialized connection."""

    def __init__(self, factory: ConnectionFactory) -> None:
        self._factory = factory

    async def probe(
        self,
        address: Address,
        *,
        deadline: float | None = None,
    ) -> ServerDescription:
        """Return one server description with measured hello round-trip time.

        Returns:
            The server description derived from hello.

        Raises:
            RuntimeError: If the factory did not complete the hello handshake.
        """
        loop = asyncio.get_running_loop()
        connection = await self._factory.create(address, deadline=deadline)
        try:
            hello: HelloResult | None = connection.hello_result
            if hello is None:
                raise RuntimeError("connection factory did not complete hello")
            finished = loop.time()
            return ServerDescription(
                address=address,
                hello=hello,
                round_trip_time=connection.hello_round_trip_time,
                updated_at=finished,
            )
        finally:
            await connection.close()
