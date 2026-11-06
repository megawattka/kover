from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kover.network.transport import Transport


async def test_send_rejects_closing_writer() -> None:
    transport = Transport("127.0.0.1", 27017)
    writer = MagicMock(spec=asyncio.StreamWriter)
    writer.is_closing.return_value = True
    with (
        patch.object(transport, "_writer", writer),
        pytest.raises(OSError, match="not connected"),
    ):
        await transport.send(b"request")


@pytest.mark.parametrize("error_type", [OSError, RuntimeError])
async def test_send_failure_propagates_without_closing_transport(
    error_type: type[Exception],
) -> None:
    transport = Transport("127.0.0.1", 27017)
    writer = MagicMock(spec=asyncio.StreamWriter)
    writer.is_closing.return_value = False
    error = error_type("send interrupted")
    writer.drain.side_effect = error
    with patch.object(transport, "_writer", writer):
        with pytest.raises(error_type) as caught:
            await transport.send(b"request")
        assert caught.value is error


async def test_receive_rejects_missing_or_closing_reader() -> None:
    transport = Transport("127.0.0.1", 27017)
    with pytest.raises(OSError, match="not connected"):
        await transport.receive(1)

    reader = MagicMock(spec=asyncio.StreamReader)
    writer = MagicMock(spec=asyncio.StreamWriter)
    writer.is_closing.return_value = True
    with (
        patch.object(transport, "_reader", reader),
        patch.object(transport, "_writer", writer),
        pytest.raises(OSError, match="not connected"),
    ):
        await transport.receive(1)
    reader.readexactly.assert_not_awaited()


async def test_connect_uses_tls_and_socket_parameters() -> None:
    transport = Transport("db", 27018, tls=True)
    reader = MagicMock()
    writer = MagicMock(spec=asyncio.StreamWriter)
    writer.is_closing.return_value = False
    with (
        patch("kover.network.transport.ssl.create_default_context") as context,
        patch(
            "kover.network.transport.asyncio.open_connection",
            return_value=(reader, writer),
        ) as open_connection,
    ):
        await transport.connect()
    assert transport.connected
    open_connection.assert_awaited_once_with(
        "db",
        27018,
        ssl=context.return_value,
        server_hostname="db",
    )


async def test_close_is_idempotent_and_closes_writer_once() -> None:
    transport = Transport("db", 27017)
    writer = MagicMock(spec=asyncio.StreamWriter)
    writer.wait_closed = AsyncMock()
    with patch.object(transport, "_writer", writer):
        await transport.close()
        await transport.close()
    writer.close.assert_called_once_with()
    writer.wait_closed.assert_awaited_once_with()
