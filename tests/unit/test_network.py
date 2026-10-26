from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
import struct
from typing import TYPE_CHECKING
import unittest
from unittest.mock import AsyncMock, patch

import bson

from kover.exceptions import OperationFailure
from kover.network.transport import MongoTransport
from kover.network.wirehelper import OP_COMPRESSED, OP_MSG, WireHelper

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from kover.typings import JsonT


class NetworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._servers: list[asyncio.Server] = []
        self._server_tasks: list[asyncio.Task[None]] = []
        self._server_errors: list[Exception] = []
        self._transports: list[MongoTransport] = []

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
            [asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None],
        ],
        *,
        tls: bool = False,
    ) -> MongoTransport:
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
        transport = MongoTransport(address[0], address[1], tls=tls)
        self._transports.append(transport)
        await transport.connect()
        return transport

    @staticmethod
    async def read_command(
        reader: asyncio.StreamReader,
    ) -> tuple[int, JsonT]:
        """Read and decode one OP_MSG command from a transport.

        Returns:
            The request id and decoded command document.

        Raises:
            AssertionError: if the message is not a kind-0 OP_MSG.
        """
        length, request_id, _, opcode = struct.unpack(
            "<iiii", await reader.readexactly(16),
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
    def reply(request_id: int, document: JsonT) -> bytes:
        """Encode an OP_MSG response for the provided request id.

        Returns:
            The complete response message, including its wire header.
        """
        payload = b"\x00" * 5 + bson.encode(document)
        return struct.pack(
            "<iiii", len(payload) + 16, 123, request_id, OP_MSG,
        ) + payload

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
        received: list[JsonT] = []

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
        assert transport.is_connected
        assert await transport.request(
            {"ping": 1}, db_name="admin",
        ) == {"ok": 1.0, "value": 42}
        assert received[0]["$db"] == "admin"
        await transport.close()
        assert not transport.is_connected

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
                writer.write(response[offset:offset + 3])
                await writer.drain()
                await asyncio.sleep(0)
            await reader.read()

        transport = await self.connect(server)
        result = await transport.request({"ping": 3})
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
        with self.assertRaises(OperationFailure):
            await transport.request({"ping": 1})

        assert transport.is_connected
        assert await transport.request({"ping": 2}) == {
            "ok": 1.0, "value": "still connected",
        }

    async def test_eof_during_reply_propagates(self) -> None:
        async def server(
            reader: asyncio.StreamReader,
            _writer: asyncio.StreamWriter,
        ) -> None:
            await self.read_command(reader)

        transport = await self.connect(server)
        with self.assertRaises(asyncio.IncompleteReadError):
            await transport.request({"ping": 1})

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
        with self.assertRaises(AssertionError):
            await transport.request({"ping": 1})

    async def test_compressed_wire_message_round_trip(self) -> None:
        helper = WireHelper()
        request_id, message = helper.get_message(
            {"ping": 1, "$db": "admin"}, compressor="zlib",
        )
        length, actual_id, _, opcode = struct.unpack("<iiii", message[:16])
        assert length == len(message)
        assert actual_id == request_id
        assert opcode == OP_COMPRESSED

        original = {"ok": 1.0, "message": "compressed"}
        with patch.object(helper, "_randint", return_value=42):
            _, compressed_reply = helper.get_message(
                original, compressor="zlib",
            )
        response = self.set_response_to(compressed_reply, 42)
        assert helper.get_reply(response[16:], OP_COMPRESSED) == original

    @staticmethod
    async def test_hello_request_builds_model_from_server_reply() -> None:
        transport = MongoTransport("localhost", 27017)
        with patch.object(
            transport, "request", new_callable=AsyncMock,
        ) as request:
            request.return_value = {
                "ok": 1.0,
                "localTime": datetime.now(UTC),
                "connectionId": 7,
                "readOnly": False,
                "isWritablePrimary": True,
                "maxWireVersion": 21,
                "maxMessageSizeBytes": 1000,
                "maxBsonObjectSize": 500,
                "setName": "rs0",
            }

            hello = await transport.hello()

        assert hello.is_primary
        assert hello.connection_id == 7
        request.assert_awaited_once()

    async def test_not_connected_transport_rejects_send(self) -> None:
        transport = MongoTransport("localhost", 27017)
        with self.assertRaises(ConnectionError):
            await transport.request({"ping": 1})

    @staticmethod
    def test_wire_helper_builds_op_msg() -> None:
        helper = WireHelper()
        request_id, message = helper.get_message(
            {"ping": 1, "$db": "admin"},
        )

        length, actual_request_id, response_to, opcode = struct.unpack(
            "<iiii", message[:16],
        )
        assert length == len(message)
        assert actual_request_id == request_id
        assert response_to == 0
        assert opcode == OP_MSG
        assert bson.decode(message[21:])["ping"] == 1  # pyright: ignore[reportUnknownMemberType]

    @staticmethod
    async def test_error_reply_is_converted_to_operation_failure() -> None:
        helper = WireHelper()
        error = await helper.get_exception({
            "ok": 0,
            "code": 13,
            "errmsg": "not authorized",
            "errorLabels": ["TransientTransactionError"],
        })

        assert isinstance(error, OperationFailure)
        assert error.code == 13

    @staticmethod
    async def test_error_types_are_cached_without_sharing_error_info() -> None:
        helper = WireHelper()
        first = await helper.get_exception({
            "code": 2,
            "errmsg": "first",
            "errInfo": {"detail": "first"},
        })
        second = await helper.get_exception({
            "code": 2,
            "errmsg": "second",
            "errInfo": {"detail": "second"},
        })

        assert type(first) is type(second)
        assert first.err_info == {"detail": "first"}
        assert second.err_info == {"detail": "second"}
