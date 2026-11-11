from __future__ import annotations

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import zlib

from elune import CodecOptions, UuidRepresentation, decode
import pytest

from kover.exceptions import PoolClosedError
from kover.models.address import Address
from kover.models.hello import HelloResult
from kover.network.factory import ConnectionFactory
from kover.network.pool import ConnectionPool
from kover.network.probe import ServerProbe
from kover.network.registry import PoolRegistry


def fake_connection(hello: HelloResult | None = None) -> MagicMock:
    connection = MagicMock()
    connection.hello_result = hello
    connection.connect = AsyncMock()
    connection.hello = AsyncMock(return_value=hello)
    connection.close = AsyncMock()
    connection.usable = True
    return connection


async def test_factory_connects_and_runs_authenticated_hello() -> None:
    address = Address(host="db")
    connection = fake_connection()
    factory = ConnectionFactory()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "kover.network.factory.Connection",
            MagicMock(return_value=connection),
        )
        monkeypatch.setattr(
            "kover.network.factory.Transport",
            MagicMock(),
        )
        created = await factory.create(address)
    assert created is connection
    connection.connect.assert_awaited_once()
    connection.hello.assert_awaited_once()


@pytest.mark.parametrize("level", [-1, 0, 9])
async def test_factory_passes_zlib_level_to_connection_codec(
    level: int,
) -> None:
    connection = fake_connection()
    constructor = MagicMock(return_value=connection)
    factory = ConnectionFactory(
        compression=["zlib"],
        zlib_compression_level=level,
    )
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("kover.network.factory.Connection", constructor)
        monkeypatch.setattr("kover.network.factory.Transport", MagicMock())
        await factory.create(Address(host="db"))
    codec = constructor.call_args.kwargs["codec"]
    command = {"insert": "items", "data": "compressible" * 1000}
    body = codec.encode(command, "shop", request_id=1)[16:]
    codec.set_compressor("zlib")
    wire = codec.encode(command, "shop", request_id=1)
    assert struct.unpack_from("<iiB", wire, 16) == (2013, len(body), 2)
    assert wire[25:] == zlib.compress(body, level=level)


async def test_factory_passes_codec_options_to_connection_codec() -> None:
    connection = fake_connection()
    constructor = MagicMock(return_value=connection)
    options = CodecOptions(uuid_representation=UuidRepresentation.STANDARD)
    factory = ConnectionFactory(codec_options=options)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("kover.network.factory.Connection", constructor)
        monkeypatch.setattr("kover.network.factory.Transport", MagicMock())
        await factory.create(Address(host="db"))
    codec = constructor.call_args.kwargs["codec"]
    value = uuid4()
    wire = codec.encode({
        "insert": "items",
        "uuid": value,
    }, "shop", request_id=1)
    assert decode(wire[21:], codec_options=options)["uuid"] == value


async def test_factory_closes_connection_when_handshake_fails() -> None:
    connection = fake_connection()
    connection.hello.side_effect = OSError("hello failed")
    factory = ConnectionFactory()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "kover.network.factory.Connection",
            MagicMock(return_value=connection),
        )
        monkeypatch.setattr("kover.network.factory.Transport", MagicMock())
        with pytest.raises(OSError, match="hello failed"):
            await factory.create(Address(host="db"))
    connection.close.assert_awaited_once()


@pytest.mark.parametrize(
    "close_failure",
    [OSError("close failed"), asyncio.CancelledError()],
)
async def test_factory_preserves_original_failure_when_cleanup_fails(
    close_failure: BaseException,
) -> None:
    connection = fake_connection()
    original = OSError("authentication failed")
    connection.hello.side_effect = original
    connection.close.side_effect = close_failure
    factory = ConnectionFactory()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "kover.network.factory.Connection",
            MagicMock(return_value=connection),
        )
        monkeypatch.setattr("kover.network.factory.Transport", MagicMock())
        with pytest.raises(OSError, match="authentication failed") as caught:
            await factory.create(Address(host="db"))

    assert caught.value is original
    assert any("cleanup" in note.lower() for note in original.__notes__)
    connection.close.assert_awaited_once()


@pytest.mark.parametrize(
    "failure",
    [OSError("connect failed"), asyncio.CancelledError()],
)
async def test_factory_closes_connection_for_any_base_exception(
    failure: BaseException,
) -> None:
    connection = fake_connection()
    connection.connect.side_effect = failure
    factory = ConnectionFactory()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "kover.network.factory.Connection",
            MagicMock(return_value=connection),
        )
        monkeypatch.setattr("kover.network.factory.Transport", MagicMock())
        with pytest.raises(type(failure)):
            await factory.create(Address(host="db"))
    connection.close.assert_awaited_once()


async def test_probe_uses_factory_hello_and_closes_probe_connection() -> None:
    hello = HelloResult.model_validate(
        {
            "localTime": "2025-01-01T00:00:00Z",
            "connectionId": 3,
            "isWritablePrimary": True,
        },
    )
    connection = fake_connection(hello)
    factory = MagicMock()
    factory.create = AsyncMock(return_value=connection)
    probe = ServerProbe(factory)
    result = await probe.probe(Address(host="db"))
    assert result.hello is hello
    assert result.address == Address(host="db")
    assert result.round_trip_time >= 0
    connection.close.assert_awaited_once()


def test_registry_returns_same_pool_for_case_insensitive_address() -> None:
    factory = MagicMock(spec=ConnectionFactory)
    registry = PoolRegistry(factory)
    first = registry.for_server(Address(host="DB.example", port=27017))
    second = registry.for_server(Address(host="db.EXAMPLE", port=27017))
    assert first is second
    assert isinstance(first, ConnectionPool)


async def test_registry_closes_pools_and_rejects_creation_afterwards() -> None:
    factory = MagicMock(spec=ConnectionFactory)
    registry = PoolRegistry(factory)
    pool = registry.for_server(Address(host="db"))
    pool.close = AsyncMock()
    await registry.close()
    await registry.close()
    pool.close.assert_awaited_once()
    with pytest.raises(PoolClosedError):
        registry.for_server(Address(host="other"))
