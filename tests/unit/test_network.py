from __future__ import annotations

import asyncio
from contextlib import suppress
import struct
from typing import TYPE_CHECKING
import unittest

import bson

from kover.exceptions import OperationFailure, ProtocolError
from kover.models.network import Address
from kover.network.codec import OP_MSG, CommandCodec
from kover.network.connection import Connection
from kover.network.error_mapper import ErrorMapper
from kover.network.transport import Transport

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from kover.typings import DictT


class NetworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._servers: list[asyncio.Server] = []
        self._server_tasks: list[asyncio.Task[None]] = []
        self._server_errors: list[Exception] = []
        self._transports: list[Transport] = []

    async def asyncTearDown(self) -> None:
        for transport in self._transports:
            await transport.close()

        for server in self._servers:
            server.close()
        for server in self._servers:
            await server.wait_closed()

        for task in self._server_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._server_tasks, return_exceptions=True)
        assert not self._server_errors, self._server_errors

    async def connect(
        self,
        handler: Callable[
            [asyncio.StreamReader, asyncio.StreamWriter],
            Awaitable[None],
        ],
        *,
        tls: bool = False,
    ) -> Transport:
        """Start a local MongoDB-wire-protocol server and connect.

        Returns:
            The connected transport.
        """

        async def serve(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            task = asyncio.current_task()
            if task is not None:
                self._server_tasks.append(task)
            try:
                await handler(reader, writer)
            except (ConnectionError, asyncio.IncompleteReadError):
                pass
            except asyncio.CancelledError:
                raise
            except (AssertionError, OSError, ValueError) as error:
                self._server_errors.append(error)
            finally:
                writer.close()
                with suppress(ConnectionError, OSError):
                    await writer.wait_closed()

        server = await asyncio.start_server(serve, "127.0.0.1", 0)
        self._servers.append(server)
        address = server.sockets[0].getsockname()
        transport = Transport(address[0], address[1], tls=tls)
        self._transports.append(transport)
        await transport.connect()
        return transport

    @staticmethod
    async def read_command(
        reader: asyncio.StreamReader,
    ) -> tuple[int, DictT]:
        """Read and decode one OP_MSG command from a transport.

        Returns:
            The request id and decoded command document.

        Raises:
            AssertionError: if the message is not a kind-0 OP_MSG.
        """
        length, request_id, _, opcode = struct.unpack(
            "<iiii",
            await reader.readexactly(16),
        )
        if opcode != OP_MSG:
            raise AssertionError(f"Expected OP_MSG, got {opcode}")
        payload = await reader.readexactly(length - 16)
        if len(payload) < 5:
            raise AssertionError("Expected a kind-0 OP_MSG section")
        if payload[4] != 0:
            raise AssertionError("Expected an OP_MSG kind-0 body section")
        return request_id, bson.decode(payload[5:])  # pyright: ignore[reportUnknownMemberType]

    @staticmethod
    def reply(request_id: int, document: DictT) -> bytes:
        """Encode an OP_MSG response for the provided request id.

        Returns:
            The complete response message, including its wire header.
        """
        payload = b"\x00" * 5 + bson.encode(document)
        return (
            struct.pack(
                "<iiii",
                len(payload) + 16,
                123,
                request_id,
                OP_MSG,
            )
            + payload
        )

    @staticmethod
    def set_response_to(message: bytes, request_id: int) -> bytes:
        """Set responseTo in an OP_COMPRESSED message header.

        Returns:
            A copy of the message with the requested response id.
        """
        response = bytearray(message)
        struct.pack_into("<i", response, 8, request_id)
        return bytes(response)

    async def test_connect_request_and_clean_close(self) -> None:
        received: list[DictT] = []

        async def server(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            request_id, command = await self.read_command(reader)
            received.append(command)
            writer.write(self.reply(request_id, {"ok": 1.0, "value": 42}))
            await writer.drain()
            await reader.read()

        transport = await self.connect(server)
        connection = Connection(
            Address(host=transport.host, port=transport.port),
            transport,
            CommandCodec(),
            ErrorMapper(),
        )
        assert transport.connected
        assert await connection.command(
            {"ping": 1},
            database="admin",
        ) == {"ok": 1.0, "value": 42}
        assert received[0]["$db"] == "admin"
        await transport.close()
        assert not transport.connected

    async def test_fragmented_reply(self) -> None:
        async def server(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            request_id, command = await self.read_command(reader)
            response = self.reply(
                request_id,
                {"ok": 1.0, "value": command["ping"]},
            )
            for offset in range(0, len(response), 3):
                writer.write(response[offset : offset + 3])
                await writer.drain()
                await asyncio.sleep(0)
            await reader.read()

        transport = await self.connect(server)
        connection = Connection(
            Address(host=transport.host, port=transport.port),
            transport,
            CommandCodec(),
            ErrorMapper(),
        )
        result = await connection.command({"ping": 3})
        assert result["value"] == 3

    async def test_command_failure_keeps_transport_reusable(self) -> None:
        async def server(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            for response in (
                {"ok": 0.0, "code": 13, "errmsg": "denied"},
                {"ok": 1.0, "value": "still connected"},
            ):
                request_id, _ = await self.read_command(reader)
                writer.write(self.reply(request_id, response))
                await writer.drain()
            await reader.read()

        transport = await self.connect(server)
        connection = Connection(
            Address(host=transport.host, port=transport.port),
            transport,
            CommandCodec(),
            ErrorMapper(),
        )
        with self.assertRaises(OperationFailure):
            await connection.command({"ping": 1})

        assert transport.connected
        assert await connection.command({"ping": 2}) == {
            "ok": 1.0,
            "value": "still connected",
        }

    async def test_eof_during_reply_propagates(self) -> None:
        async def server(
            reader: asyncio.StreamReader,
            _writer: asyncio.StreamWriter,
        ) -> None:
            await self.read_command(reader)

        transport = await self.connect(server)
        connection = Connection(
            Address(host=transport.host, port=transport.port),
            transport,
            CommandCodec(),
            ErrorMapper(),
        )
        with self.assertRaises(asyncio.IncompleteReadError):
            await connection.command({"ping": 1})

    async def test_invalid_response_request_id_is_rejected(self) -> None:
        async def server(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            request_id, _ = await self.read_command(reader)
            response = bytearray(self.reply(request_id, {"ok": 1.0}))
            struct.pack_into("<i", response, 8, request_id + 1)
            writer.write(response)
            await writer.drain()

        transport = await self.connect(server)
        connection = Connection(
            Address(host=transport.host, port=transport.port),
            transport,
            CommandCodec(),
            ErrorMapper(),
        )
        with self.assertRaises(ProtocolError):
            await connection.command({"ping": 1})

    async def test_not_connected_transport_rejects_both_send_paths(
        self,
    ) -> None:
        transport = Transport("127.0.0.1", 27017)
        with self.assertRaises(ConnectionError):
            await transport.exchange(b"request")
        with self.assertRaises(ConnectionError):
            await transport.exchange_without_reply(b"request")
        await transport.close()

    async def test_connect_is_idempotent(self) -> None:
        async def server(
            reader: asyncio.StreamReader,
            _writer: asyncio.StreamWriter,
        ) -> None:
            await reader.read()

        transport = await self.connect(server)
        await transport.connect()
        assert transport.connected
        await transport.close()
        await transport.close()
        assert not transport.connected

    async def test_invalid_message_lengths_abort_transport(self) -> None:
        for length in (-1, 0, 15, 49 * 1024 * 1024):

            async def server(
                reader: asyncio.StreamReader,
                writer: asyncio.StreamWriter,
                length: int = length,
            ) -> None:
                await self.read_command(reader)
                writer.write(struct.pack("<i", length))
                await writer.drain()

            transport = await self.connect(server)
            request = CommandCodec().encode({"ping": 1}, "test", request_id=1)
            with self.assertRaisesRegex(ValueError, "message length"):
                await transport.exchange(request)
            assert not transport.connected

    async def test_deadline_and_cancellation_abort_incomplete_exchange(
        self,
    ) -> None:
        async def server(
            reader: asyncio.StreamReader,
            _writer: asyncio.StreamWriter,
        ) -> None:
            await self.read_command(reader)
            await reader.read()

        request = CommandCodec().encode({"ping": 1}, "test", request_id=1)
        transport = await self.connect(server)
        with self.assertRaises(TimeoutError):
            await transport.exchange(
                request,
                deadline=asyncio.get_running_loop().time() + 0.01,
            )
        assert not transport.connected
        transport = await self.connect(server)
        task = asyncio.create_task(transport.exchange(request))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        assert not transport.connected

    async def test_send_without_reply_and_expired_deadline(self) -> None:
        received = asyncio.Event()

        async def server(
            reader: asyncio.StreamReader,
            _writer: asyncio.StreamWriter,
        ) -> None:
            _, command = await self.read_command(reader)
            assert command["ping"] == 1
            received.set()
            await reader.read()

        request = CommandCodec().encode({"ping": 1}, "test", request_id=1)
        for deadline in (None, asyncio.get_running_loop().time() + 1):
            received.clear()
            transport = await self.connect(server)
            await transport.exchange_without_reply(request, deadline=deadline)
            await asyncio.wait_for(received.wait(), 1)
            assert transport.connected
            await transport.close()
        transport = await self.connect(server)
        with self.assertRaises(TimeoutError):
            await transport.exchange_without_reply(
                request,
                deadline=asyncio.get_running_loop().time() - 1,
            )
        assert not transport.connected
