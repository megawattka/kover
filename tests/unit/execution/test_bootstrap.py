from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from elune import CodecOptions, UuidRepresentation
import pytest

from kover.bootstrap import from_uri, make_client
from kover.client import Kover
from kover.models.address import Address
from kover.models.concerns import WriteConcern
from kover.models.credentials import AuthCredentials
from kover.models.read_preference import ReadPreference


async def test_make_client_composes_and_selects_server() -> None:
    password_value = "secret"  # ruff: ignore[hardcoded-password-string]
    credentials = AuthCredentials(username="user", password=password_value)
    preference = ReadPreference(mode="secondary")
    concern = WriteConcern(w=2, j=True)
    codec_options = CodecOptions(
        uuid_representation=UuidRepresentation.STANDARD,
    )
    with (
        patch(
            "kover.bootstrap.ConnectionFactory",
            autospec=True,
        ) as factory,
        patch("kover.bootstrap.ServerProbe", autospec=True) as probe,
        patch(
            "kover.bootstrap.ServerDiscovery",
            autospec=True,
        ) as discovery,
        patch("kover.bootstrap.ServerSelector", autospec=True) as selector,
        patch("kover.bootstrap.PoolRegistry", autospec=True) as pools,
        patch("kover.bootstrap.CommandExecutor", autospec=True) as executor,
    ):
        client = await make_client(
            "db",
            27018,
            credentials=credentials,
            compression=("zlib",),
            zlib_compression_level=9,
            tls=True,
            application={"name": "test"},
            replica_set="rs",
            read_preference=preference,
            server_selection_timeout=2,
            connect_timeout=None,
            local_threshold=0.02,
            max_pool_size=5,
            write_concern=concern,
            codec_options=codec_options,
        )
        assert isinstance(client, Kover)
        factory.assert_called_once_with(
            credentials=credentials,
            tls=True,
            compression=["zlib"],
            zlib_compression_level=9,
            application={"name": "test"},
            loop=None,
            codec_options=codec_options,
        )
        probe.assert_called_once_with(factory.return_value)
        settings = discovery.call_args.kwargs["options"]
        assert discovery.call_args.args[0] == [Address(host="db", port=27018)]
        assert discovery.call_args.kwargs["probe"] is probe.return_value
        assert settings.replica_set == "rs"
        assert settings.connect_timeout is None
        assert settings.server_selection_timeout == 2
        assert settings.local_threshold == pytest.approx(0.02)
        selector.assert_called_once_with(
            discovery.return_value,
            options=settings,
        )
        selector.return_value.select.assert_awaited_once_with(preference)
        pools.assert_called_once_with(
            factory.return_value,
            max_pool_size=5,
            connection_timeout=None,
        )
        executor.assert_called_once_with(
            selector=selector.return_value,
            pools=pools.return_value,
            default_preference=preference,
        )
        await client.command({"insert": "items"})
        assert (
            executor.return_value.execute.await_args.kwargs["write_concern"]
            is concern
        )
        await client.close()
        executor.return_value.close.assert_awaited_once_with()


async def test_from_uri_preserves_all_seeds_and_normalized_options() -> None:
    codec_options = CodecOptions(
        uuid_representation=UuidRepresentation.STANDARD,
    )
    with patch(
        "kover.bootstrap._build_client",
        new_callable=AsyncMock,
    ) as build:
        client = await from_uri(
            "mongodb://user:other-secret@one:27018,two:27019/authdb"
            "?replicaSet=rs&tls=true&compressors=zlib&appName=test"
            "&serverSelectionTimeoutMS=2500&connectTimeoutMS=0"
            "&localThresholdMS=20&maxPoolSize=7&w=2&journal=true"
            "&wTimeoutMS=125&readPreference=secondary"
            "&readPreferenceTags=region:eu&maxStalenessSeconds=120"
            "&zlibCompressionLevel=0",
            codec_options=codec_options,
        )
    assert client is build.return_value
    args = build.call_args
    assert args.kwargs["codec_options"] is codec_options
    assert args.args[0] == [
        Address(host="one", port=27018),
        Address(host="two", port=27019),
    ]
    settings = args.kwargs["options"]
    assert settings.server_selection_timeout == pytest.approx(2.5)
    assert settings.connect_timeout is None
    assert settings.local_threshold == pytest.approx(0.02)
    assert settings.replica_set == "rs"
    assert settings.read_preference == ReadPreference(
        mode="secondary",
        tag_sets=({"region": "eu"},),
        max_staleness_seconds=120,
    )
    assert args.kwargs["credentials"] == AuthCredentials(
        username="user",
        password="other-secret",  # ruff: ignore[hardcoded-password-func-arg]
        auth_database="authdb",
    )
    assert args.kwargs["write_concern"] == WriteConcern(
        w=2,
        j=True,
        wtimeout=125,
    )
    assert args.kwargs["max_pool_size"] == 7
    assert args.kwargs["compression"] == ["zlib"]
    assert args.kwargs["zlib_compression_level"] == 0
    assert args.kwargs["application"] == {"name": "test"}
    assert args.kwargs["tls"] is True


async def test_from_uri_defaults_and_explicit_auth_source() -> None:
    with patch(
        "kover.bootstrap._build_client",
        new_callable=AsyncMock,
    ) as build:
        await from_uri("mongodb://user:password@db/shop?authSource=users")
    settings = build.call_args.kwargs["options"]
    assert settings.server_selection_timeout == 30
    assert settings.connect_timeout == 10
    assert settings.read_preference == ReadPreference()
    assert build.call_args.kwargs["credentials"].auth_database == "users"
    assert build.call_args.kwargs["zlib_compression_level"] == -1
    assert build.call_args.kwargs["codec_options"] is None


async def test_from_uri_rejects_load_balancing_before_building() -> None:
    with (
        patch(
            "kover.bootstrap._build_client",
            new_callable=AsyncMock,
        ) as build,
        pytest.raises(ValueError, match="loadBalanced"),
    ):
        await from_uri("mongodb://db/?loadBalanced=true")
    build.assert_not_awaited()


@pytest.mark.parametrize(
    "error",
    [TimeoutError("no server"), asyncio.CancelledError()],
)
async def test_initial_selection_failure_closes_executor(
    error: BaseException,
) -> None:
    with (
        patch("kover.bootstrap.ServerSelector", autospec=True) as selector,
        patch("kover.bootstrap.CommandExecutor", autospec=True) as executor,
    ):
        selector.return_value.select.side_effect = error
        with pytest.raises(type(error)) as caught:
            await make_client()
        assert caught.value is error
        executor.return_value.close.assert_awaited_once_with()


async def test_real_composition_without_opening_pools() -> None:
    with patch(
        "kover.bootstrap.ServerSelector.select",
        new_callable=AsyncMock,
        return_value=Address(host="db"),
    ):
        client = await make_client("db")
    await client.close()


async def test_invalid_pool_size_is_rejected_before_selection() -> None:
    with (
        patch(
            "kover.bootstrap.ServerSelector.select",
            new_callable=AsyncMock,
        ) as select,
        pytest.raises(ValueError, match="max_pool_size"),
    ):
        await make_client(max_pool_size=0)
    select.assert_not_awaited()


@pytest.mark.parametrize("level", [-2, 10])
async def test_invalid_zlib_level_is_rejected_before_selection(
    level: int,
) -> None:
    with (
        patch(
            "kover.bootstrap.ServerSelector.select",
            new_callable=AsyncMock,
        ) as select,
        pytest.raises(ValueError, match="level"),
    ):
        await make_client(zlib_compression_level=level)
    select.assert_not_awaited()
