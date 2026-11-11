from __future__ import annotations

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from elune import encode
import pytest

from kover.client import Kover
from kover.exceptions import NetworkError, ProtocolError
from kover.execution.executor import CommandExecutor
from kover.models.address import Address
from kover.network.connection import Connection
from kover.network.transport import Transport


def response(
    *,
    request_id: int = 1,
    body: bytes | None = None,
    opcode: int = 2013,
) -> bytes:
    if body is None:
        body = struct.pack("<iB", 0, 0) + encode({"ok": 1})
    return struct.pack("<iiii", 16 + len(body), 9, request_id, opcode) + body


@pytest.mark.parametrize(
    ("message", "error_type"),
    [
        (b"\x20", NetworkError),
        (response()[:-1], NetworkError),
        (struct.pack("<i", 15), ProtocolError),
        (struct.pack("<i", 49 * 1024 * 1024), ProtocolError),
        (response(request_id=99), ProtocolError),
        (response(body=struct.pack("<iB", 0, 1)), ProtocolError),
        (response(body=struct.pack("<iB", 0, 0) + b"bad"), ProtocolError),
        (
            response(
                body=struct.pack("<iiB", 2013, 13, 2) + b"bad",
                opcode=2012,
            ),
            ProtocolError,
        ),
    ],
    ids=[
        "short-prefix",
        "short-body",
        "short-length",
        "large-length",
        "wrong-id",
        "wrong-section",
        "invalid-bson",
        "invalid-zlib",
    ],
)
@pytest.mark.parametrize("close_fails", [False, True])
async def test_invalid_reply_closes_connection_and_invalidates_server(
    message: bytes,
    error_type: type[Exception],
    *,
    close_fails: bool,
) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(message)
    reader.feed_eof()
    transport = MagicMock(spec=Transport)
    transport.connected = True
    transport.send = AsyncMock()
    transport.receive = AsyncMock(side_effect=reader.readexactly)
    transport.close = AsyncMock()
    if close_fails:
        transport.close.side_effect = OSError("close failed")
    address = Address(host="db")
    connection = Connection(address, transport)
    selector = MagicMock()
    selector.select = AsyncMock(return_value=address)
    pools = MagicMock()
    pools.for_server.return_value.execute = AsyncMock(
        side_effect=connection.command,
    )
    pools.close = AsyncMock()
    client = Kover(CommandExecutor(selector=selector, pools=pools))
    try:
        with pytest.raises(error_type) as caught:
            await client.command({"ping": 1})
        if message != struct.pack("<i", 49 * 1024 * 1024):
            assert caught.value.__cause__ is not None
        if close_fails:
            assert any(
                "close failed" in note for note in caught.value.__notes__
            )
        assert not connection.usable
        transport.close.assert_awaited_once()
        selector.invalidate.assert_called_once_with(address)
    finally:
        await client.close()


@pytest.mark.parametrize("failure", [TimeoutError(), asyncio.CancelledError()])
async def test_exchange_failure_survives_cleanup_failure(
    failure: BaseException,
) -> None:
    transport = MagicMock(spec=Transport)
    transport.send = AsyncMock(side_effect=failure)
    transport.close = AsyncMock(side_effect=OSError("close failed"))
    connection = Connection(Address(host="db"), transport)
    with pytest.raises(type(failure)) as caught:
        await connection.command({"ping": 1})
    assert caught.value is failure
    assert not connection.usable
    transport.close.assert_awaited_once()


@pytest.mark.parametrize(
    ("value", "error_type"),
    [(2**100, OverflowError), (uuid4(), ValueError)],
)
async def test_encoding_error_keeps_connection_and_server_usable(
    value: object,
    error_type: type[Exception],
) -> None:
    transport = MagicMock(spec=Transport)
    transport.connected = True
    transport.send = AsyncMock()
    transport.close = AsyncMock()
    address = Address(host="db")
    connection = Connection(address, transport)
    selector = MagicMock()
    selector.select = AsyncMock(return_value=address)
    pools = MagicMock()
    pools.for_server.return_value.execute = AsyncMock(
        side_effect=connection.command,
    )
    pools.close = AsyncMock()
    client = Kover(CommandExecutor(selector=selector, pools=pools))
    try:
        with pytest.raises(error_type):
            await client.command({"insert": "items", "value": value})
        assert connection.usable
        transport.send.assert_not_awaited()
        transport.close.assert_not_awaited()
        selector.invalidate.assert_not_called()
    finally:
        await client.close()
