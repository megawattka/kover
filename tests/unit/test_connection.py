from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kover import AuthCredentials
from kover.exceptions import ConnectionClosedError, NetworkError, ProtocolError
from kover.models.network import Address
from kover.network.auth import Auth
from kover.network.codec import CommandCodec
from kover.network.connection import Connection
from kover.network.error_mapper import ErrorMapper
from kover.network.transport import Transport


def connection_mock() -> tuple[Connection, MagicMock, MagicMock]:
    transport = MagicMock(spec=Transport)
    transport.connected = True
    codec = MagicMock(spec=CommandCodec)
    codec.encode.return_value = b"request"
    codec.decode.return_value = {"ok": 1}
    connection = Connection(
        Address(host="localhost"), transport, codec, ErrorMapper(),
    )
    return connection, transport, codec


async def test_command_delegation_ids_deadline_and_database() -> None:
    connection, transport, codec = connection_mock()
    await connection.connect()
    transport.connect.assert_awaited_once()
    assert await connection.command({"ping": 1}, "test", deadline=42) == {
        "ok": 1,
    }
    codec.encode.assert_called_with({"ping": 1}, "test", request_id=1)
    transport.exchange.assert_awaited_with(b"request", deadline=42)
    assert codec.decode.call_args.kwargs == {"expected_response_to": 1}
    await connection.command({"ping": 2}, database="other")
    codec.encode.assert_called_with({"ping": 2}, "other", request_id=2)
    assert connection.address == Address(host="localhost")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ValueError("bad wire"), ProtocolError),
        (OSError("broken socket"), NetworkError),
        (asyncio.CancelledError(), asyncio.CancelledError),
        (RuntimeError("unexpected"), RuntimeError),
        (BaseException("interrupted"), BaseException),
    ],
)
async def test_exchange_failures_abort(
    error: BaseException, expected: type[BaseException],
) -> None:
    connection, transport, _ = connection_mock()
    transport.exchange.side_effect = error
    with pytest.raises(expected):
        await connection.command({"ping": 1})
    transport.abort.assert_called_once()
    assert not connection.usable
    with pytest.raises(ConnectionClosedError):
        await connection.command({"ping": 1})
    with pytest.raises(ConnectionClosedError):
        await connection.fire_and_forget({"ping": 1})


async def test_fire_and_forget_does_not_read_and_aborts_on_failure() -> None:
    connection, transport, _ = connection_mock()
    await connection.fire_and_forget({"shutdown": 1}, "test", deadline=42)
    transport.exchange_without_reply.assert_awaited_once_with(
        b"request", deadline=42,
    )
    transport.exchange.assert_not_awaited()
    transport.exchange_without_reply.side_effect = OSError("write failed")
    with pytest.raises(OSError, match="write failed"):
        await connection.fire_and_forget({"shutdown": 1})
    assert not connection.usable


async def test_hello_negotiates_compression_and_applies_credentials() -> None:
    connection, _, codec = connection_mock()
    credentials = AuthCredentials(
        username="user", password="password", auth_database="auth",
    )
    reply = {
        "ok": 1,
        "localTime": datetime.now(UTC),
        "connectionId": 7,
        "isWritablePrimary": True,
        "compression": ["zlib"],
    }
    with (
        patch.object(
            connection, "command", new=AsyncMock(return_value=reply),
        ) as command,
        patch(
            "kover.network.connection.get_hello_payload",
            return_value={"hello": 1},
        ) as hello_payload,
    ):
        hello = await connection.hello(["zlib"], credentials, {"name": "test"})
        hello_payload.assert_called_once_with(["zlib"], {"name": "test"})
        assert hello.connection_id == 7
        assert hello.is_primary
        command.assert_awaited_once_with(
            {"hello": 1, "saslSupportedMechs": "auth.user"},
        )
    codec.set_compressor.assert_called_once_with("zlib")


async def test_fire_and_forget_cancellation_invalidates_connection() -> None:
    connection, transport, _ = connection_mock()
    transport.exchange_without_reply.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await connection.fire_and_forget({"ping": 1})
    transport.abort.assert_called_once()
    assert not connection.usable
    with pytest.raises(ConnectionClosedError):
        await connection.command({"ping": 1})


async def test_authorize_delegates_and_skips_missing_credentials() -> None:
    connection, _, _ = connection_mock()
    credentials = AuthCredentials(username="user", password="password")
    with patch.object(Auth, "create", return_value=b"signature") as create:
        assert await connection.authorize(None, credentials) is None
        assert await connection.authorize("SCRAM-SHA-256", None) is None
        create.assert_not_awaited()
        assert (
            await connection.authorize("SCRAM-SHA-256", credentials)
            == b"signature"
        )
        create.assert_awaited_once_with("SCRAM-SHA-256", credentials)
    connection.abort()
    connection.abort()
    await connection.close()
