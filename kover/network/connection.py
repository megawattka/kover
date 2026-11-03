"""Command-level connection above byte transport and wire codec."""

from __future__ import annotations

from itertools import count
from typing import TYPE_CHECKING, Literal

from ..exceptions import ConnectionClosedError, NetworkError, ProtocolError
from ..helpers import get_hello_payload
from ..models import HelloResult
from .auth import Auth

if TYPE_CHECKING:
    from ..models.network import Address
    from ..typings import DictT
    from .auth import AuthCredentials
    from .codec import CommandCodec
    from .error_mapper import ErrorMapper
    from .transport import Transport


class Connection:
    """Execute one exclusive request/response at a time."""

    def __init__(
        self,
        address: Address,
        transport: Transport,
        codec: CommandCodec,
        err_mapper: ErrorMapper,
    ) -> None:
        self._address = address
        self._transport = transport
        self._codec = codec
        self._err_mapper = err_mapper
        self._request_ids = count(1)
        self._closed = False

    @property
    def address(self) -> Address:
        """Server address."""
        return self._address

    @property
    def usable(self) -> bool:
        """Local usability, not a server health check."""
        return not self._closed and self._transport.connected

    async def connect(self) -> None:
        """Connect the underlying transport."""
        await self._transport.connect()

    def abort(self) -> None:
        """Synchronously invalidate this connection."""
        if self._closed:
            return
        self._closed = True
        self._transport.abort()

    async def close(self) -> None:
        """Close this connection idempotently."""
        self.abort()
        await self._transport.close()

    async def command(
        self,
        document: DictT,
        database: str = "admin",
        *,
        deadline: float | None = None,
    ) -> DictT:
        """Encode, exchange and validate one command.

        Returns:
            The decoded server response after checking command and write
            errors.

        Raises:
            ConnectionClosedError: If this connection has been closed.
            NetworkError: If the transport exchange fails with an I/O error.
            ProtocolError: If the response framing or payload is invalid.
        """
        if self._closed:
            raise ConnectionClosedError("connection is closed")

        request_id = next(self._request_ids) % (2**31)
        request = self._codec.encode(document, database, request_id=request_id)
        exchanged = False
        try:
            message = await self._transport.exchange(
                request, deadline=deadline,
            )
            reply = self._codec.decode(
                message, expected_response_to=request_id,
            )
            exchanged = True
        except ValueError as error:
            raise ProtocolError(str(error)) from error

        except OSError as error:
            raise NetworkError(str(error)) from error
        finally:
            # Cancellation and unexpected failures leave framing uncertain.
            if not exchanged:
                self.abort()

        await self._err_mapper.check_writes(reply)
        await self._err_mapper.check(reply)
        return reply

    async def fire_and_forget(
        self,
        document: DictT,
        database: str = "admin",
        *,
        deadline: float | None = None,
    ) -> None:
        """Send a command without waiting for a reply.

        Raises:
            ConnectionClosedError: If this connection has been closed.
        """
        if self._closed:
            raise ConnectionClosedError("connection is closed")

        request_id = next(self._request_ids) % (2**31)
        request = self._codec.encode(document, database, request_id=request_id)
        sent = False
        try:
            await self._transport.exchange_without_reply(
                request,
                deadline=deadline,
            )
            sent = True
        finally:
            if not sent:
                self.abort()

    async def hello(
        self,
        compression: list[str] | None,
        credentials: AuthCredentials | None,
        application: DictT | None,
    ) -> HelloResult:
        """Perform hello and negotiate compression.

        Returns:
            The validated server hello response.
        """
        payload = get_hello_payload(compression, application)
        if credentials is not None:
            credentials.apply_to(payload)

        reply = await self.command(payload)
        hello = HelloResult.model_validate(reply)

        if hello.compression:
            self._codec.set_compressor(hello.compression[0])

        return hello

    async def authorize(
        self,
        mechanism: Literal["SCRAM-SHA-256", "SCRAM-SHA-1"] | None,
        credentials: AuthCredentials | None,
    ) -> bytes | None:
        """Authenticate through this connection.

        Returns:
            The verified SCRAM server signature, or None if the mechanism
            or credentials are absent.
        """
        if mechanism is None or credentials is None:
            return None

        return await Auth(self).create(mechanism, credentials)
