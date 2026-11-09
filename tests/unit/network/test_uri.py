from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

from dns.exception import Timeout
import dns.rdata
from dns.resolver import NXDOMAIN, NoAnswer
import pytest

from kover.network.uri_parser import parse_host, parse_uri


async def test_defaults() -> None:
    parsed = await parse_uri("mongodb://LOCALHOST")
    assert parsed.node_list == [("localhost", 27017)]
    assert parsed.username is None
    assert parsed.password is None
    assert parsed.credentials is None
    assert parsed.database is None
    assert parsed.collection is None
    assert parsed.options == {}
    assert parsed.fqdn is None


async def test_seed_list_and_ipv6() -> None:
    parsed = await parse_uri(
        "mongodb://DB1:27018,[::1],DB2,[2001:DB8::1]:27019/shop.items",
    )
    assert parsed.node_list == [
        ("db1", 27018),
        ("::1", 27017),
        ("db2", 27017),
        ("2001:db8::1", 27019),
    ]
    assert parsed.database == "shop"
    assert parsed.collection == "items"


async def test_percent_encoding_and_hidden_password() -> None:
    parsed = await parse_uri(
        "mongodb://us%40er:p%3Aa%24%2F%3F%23%5B%5D%40%25%2B@host/caf%C3%A9"
        "?AUTHSOURCE=auth&AppName=worker+one",
    )
    assert parsed.username == "us@er"
    assert parsed.password == "p:a$/?#[]@%+"  # ruff: ignore[hardcoded-password-string]
    assert parsed.database == "café"
    assert parsed.options == {"authSource": "auth", "appname": "worker one"}
    assert parsed.credentials is not None
    assert parsed.credentials.auth_database == "auth"
    assert parsed.password not in repr(parsed)


@pytest.mark.parametrize(
    ("uri", "database", "password"),
    [
        ("mongodb://user:secret@host/", "admin", "secret"),
        ("mongodb://user@host/shop", "shop", ""),
        ("mongodb://user:@host/shop?authSource=users", "users", ""),
        ("mongodb://user@host/?authMechanism=GSSAPI", "$external", ""),
        ("mongodb://user@host/?authMechanism=PLAIN", "$external", ""),
    ],
)
async def test_credentials_defaults(
    uri: str,
    database: str,
    password: str,
) -> None:
    parsed = await parse_uri(uri)
    assert parsed.credentials is not None
    assert parsed.credentials.auth_database == database
    assert parsed.credentials.password == password


async def test_typed_options_and_units() -> None:
    parsed = await parse_uri(
        "mongodb://host/?SSL=true;RETRYWRITES=false;w=2;journal=true"
        ";wTimeoutMS=125;connectTimeoutMS=2500;serverSelectionTimeoutMS=0"
        ";socketTimeoutMS=12.5;localThresholdMS=20;maxPoolSize=7;minPoolSize=2"
        ";compressors=zlib,zstd;readPreference=secondary"
        ";readPreferenceTags=region:eu,rack:one;readPreferenceTags="
        ";maxStalenessSeconds=120;authMechanismProperties=SERVICE_NAME:mongodb",
    )
    assert parsed.options == {
        "tls": True,
        "retryWrites": False,
        "w": 2,
        "journal": True,
        "wTimeoutMS": 125,
        "connectTimeoutMS": 2.5,
        "serverSelectionTimeoutMS": 0,
        "socketTimeoutMS": 0.0125,
        "localThresholdMS": 20,
        "maxPoolSize": 7,
        "minPoolSize": 2,
        "compressors": ["zlib", "zstd"],
        "readPreference": "secondary",
        "readPreferenceTags": [{"region": "eu", "rack": "one"}, {}],
        "maxStalenessSeconds": 120,
        "authMechanismProperties": {"SERVICE_NAME": "mongodb"},
    }


@pytest.mark.parametrize(
    "uri",
    [
        "",
        "http://host",
        "mongodb://",
        "mongodb://,host",
        "mongodb://host,",
        "mongodb://host,,other",
        "mongodb://:27017",
        "mongodb://host:",
        "mongodb://host:0",
        "mongodb://host:65536",
        "mongodb://host:-1",
        "mongodb://host:1.5",
        "mongodb://host:\uff11\uff12",
        "mongodb://::1",
        "mongodb://[::1",
        "mongodb://[nope]",
        "mongodb://[::1]junk",
        "mongodb://[::1]:",
        "mongodb://[::1]:2:3",
        "mongodb://ho st",
        "mongodb://host\n",
        "mongodb://host/#fragment",
        "mongodb://host/db/collection",
        "mongodb://host/bad%20db",
        "mongodb://host/bad%24db",
        "mongodb://host/%00",
        "mongodb://host/%FF",
        "mongodb://host/%ZZ",
        "mongodb://host/%",
        "mongodb://:pass@host",
        "mongodb://user:p@ss@host",
        "mongodb://user:pa:ss@host",
        "mongodb://user:p$ss@host",
        "mongodb://user:%FF@host",
        "mongodb://user:%00@host",
        "mongodb://host/?unknown=1",
        "mongodb://host/?tls=TRUE",
        "mongodb://host/?tls=1",
        "mongodb://host/?tls=true&TLS=false",
        "mongodb://host/?ssl=true&tls=true",
        "mongodb://host/?authSource=",
        "mongodb://host/?tls",
        "mongodb://host/?=value",
        "mongodb://host/?tls=true&",
        "mongodb://host/?tls=true&x=1;y=2",
        "mongodb://host/?maxPoolSize=-1",
        "mongodb://host/?maxPoolSize=1.5",
        "mongodb://host/?maxConnecting=0",
        "mongodb://host/?w=-1",
        "mongodb://host/?w=",
        "mongodb://host/?w=0&journal=true",
        "mongodb://host/?wTimeoutMS=-1",
        "mongodb://host/?connectTimeoutMS=NaN",
        "mongodb://host/?connectTimeoutMS=1_000",
        "mongodb://host/?connectTimeoutMS=inf",
        "mongodb://host/?serverSelectionTimeoutMS=-1",
        "mongodb://host/?heartbeatFrequencyMS=499",
        "mongodb://host/?localThresholdMS=-1",
        "mongodb://host/?compressors=bad",
        "mongodb://host/?readPreference=wrong",
        "mongodb://host/?maxStalenessSeconds=89",
        "mongodb://host/?readPreferenceTags=a:b",
        "mongodb://host/?authMechanism=BAD",
        "mongodb://host/?readPreference=secondary&readPreferenceTags=broken",
        "mongodb://host/?readPreference=secondary&readPreferenceTags=a:b,a:c",
        "mongodb://host/?authMechanism=GSSAPI&authSource=admin",
        "mongodb://host/?minPoolSize=10&maxPoolSize=5",
        "mongodb://one,two/?directConnection=true",
        "mongodb://one,two/?loadBalanced=true",
        "mongodb://host/?loadBalanced=true&replicaSet=rs",
        "mongodb://host/?loadBalanced=true&directConnection=true",
        "mongodb://host/?srvMaxHosts=1",
        "mongodb://host/?srvServiceName=custom",
        "mongodb://host/?tlsInsecure=true&tlsAllowInvalidCertificates=true",
        "mongodb://host/?zlibCompressionLevel=10",
        "mongodb://host/?uuidRepresentation=invalid",
        "mongodb://host/?serverMonitoringMode=invalid",
        "mongodb://host/?readConcernLevel=invalid",
    ],
)
async def test_invalid_uris(uri: str) -> None:
    with pytest.raises(ValueError, match=r".+"):
        await parse_uri(uri)


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb://%2Ftmp%2Fmongo.sock",
        "mongodb://%2Ftmp%2Fmongo.sock,host",
        "mongodb:///tmp/mongo.sock",
        "mongodb://mongo.sock",
        "mongodb://user:pass@%2Ftmp%2Fmongo.sock/db",
    ],
)
async def test_unix_sockets_are_explicitly_rejected(uri: str) -> None:
    with pytest.raises(ValueError, match="Unix domain sockets"):
        await parse_uri(uri)


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("DB:27018", ("db", 27018)),
        ("DB", ("db", 27017)),
        ("[::1]", ("::1", 27017)),
    ],
)
def test_discovery_host_parser(
    address: str,
    expected: tuple[str, int],
) -> None:
    assert parse_host(address) == expected


async def test_no_dns_for_standard_uri() -> None:
    with patch("dns.asyncresolver.resolve", new_callable=AsyncMock) as resolve:
        await parse_uri("mongodb://host/")
    resolve.assert_not_awaited()


def srv_records(*targets: str) -> list[Any]:
    return [
        dns.rdata.from_text("IN", "SRV", f"0 0 27018 {target}.")
        for target in targets
    ]


def txt_records(*texts: str) -> list[Any]:
    return [dns.rdata.from_text("IN", "TXT", text) for text in texts]


async def test_srv_and_txt_with_uri_precedence() -> None:
    records = srv_records("db1.example.com", "db2.example.com")
    txt = txt_records('"authSource=users&replica" "Set=rs"')
    with patch(
        "dns.asyncresolver.resolve",
        new_callable=AsyncMock,
        side_effect=[records, txt],
    ) as resolve:
        parsed = await parse_uri(
            "mongodb+srv://user:pass@Cluster.Example.com/shop"
            "?authSource=override&connectTimeoutMS=2500",
        )
    assert parsed.node_list == [
        ("db1.example.com", 27018),
        ("db2.example.com", 27018),
    ]
    assert parsed.fqdn == "cluster.example.com"
    assert parsed.options["tls"] is True
    assert parsed.options["replicaSet"] == "rs"
    assert parsed.credentials is not None
    assert parsed.credentials.auth_database == "override"
    assert resolve.await_args_list[0].args == (
        "_mongodb._tcp.cluster.example.com",
        "SRV",
    )
    assert resolve.await_args_list[0].kwargs == {
        "lifetime": 2.5,
        "search": False,
    }
    assert resolve.await_args_list[1].args == ("cluster.example.com", "TXT")


@pytest.mark.parametrize("missing", [NoAnswer(), NXDOMAIN()])
async def test_srv_without_txt(missing: Exception) -> None:
    with patch(
        "dns.asyncresolver.resolve",
        new_callable=AsyncMock,
        side_effect=[srv_records("db.example.com"), missing],
    ):
        parsed = await parse_uri(
            "mongodb+srv://example.com/?ssl=false&srvServiceName=custom",
        )
    assert parsed.options["tls"] is False
    assert parsed.node_list == [("db.example.com", 27018)]


async def test_srv_host_limit() -> None:
    with patch(
        "dns.asyncresolver.resolve",
        new_callable=AsyncMock,
        side_effect=[
            srv_records(
                "db1.example.com",
                "db2.example.com",
                "db3.example.com",
            ),
            NoAnswer(),
        ],
    ):
        parsed = await parse_uri(
            "mongodb+srv://cluster.example.com/?srvMaxHosts=2",
        )
    assert len(parsed.node_list) == 2
    assert len(set(parsed.node_list)) == 2
    assert set(parsed.node_list) <= {
        ("db1.example.com", 27018),
        ("db2.example.com", 27018),
        ("db3.example.com", 27018),
    }


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb+srv://localhost",
        "mongodb+srv://127.0.0.1",
        "mongodb+srv://[::1]",
        "mongodb+srv://cluster.example.com:27017",
        "mongodb+srv://a.example.com,b.example.com",
        "mongodb+srv://cluster.example.com/?directConnection=true",
        "mongodb+srv://cluster.example.com/?srvMaxHosts=1&replicaSet=rs",
        "mongodb+srv://cluster.example.com/?srvMaxHosts=1&loadBalanced=true",
        "mongodb+srv://cluster.example.com/?srvServiceName=a.b",
    ],
)
async def test_invalid_srv_uris_do_not_query_dns(uri: str) -> None:
    with (
        patch("dns.asyncresolver.resolve", new_callable=AsyncMock) as resolve,
        pytest.raises(ValueError, match=r".+"),
    ):
        await parse_uri(uri)
    resolve.assert_not_awaited()


@pytest.mark.parametrize(
    "responses",
    [
        [Timeout()],
        [srv_records("db.example.com"), Timeout()],
        [[], NoAnswer()],
        [srv_records("evil.com"), NoAnswer()],
        [srv_records("db.notexample.com"), NoAnswer()],
        [srv_records("db.example.com.evil.com"), NoAnswer()],
        [srv_records("example.com"), NoAnswer()],
        [srv_records("db.example.com"), txt_records('"tls=false"')],
        [
            srv_records("db.example.com"),
            txt_records('"authSource=a"', '"authSource=b"'),
        ],
        [
            srv_records("db.example.com"),
            txt_records('"replicaSet=rs&loadBalanced=true"'),
        ],
    ],
)
async def test_invalid_dns_records(responses: list[Any]) -> None:
    with (
        patch(
            "dns.asyncresolver.resolve",
            new_callable=AsyncMock,
            side_effect=responses,
        ),
        pytest.raises(ValueError, match=r".+"),
    ):
        await parse_uri("mongodb+srv://cluster.example.com/")


async def test_srv_cancellation_propagates() -> None:
    with (
        patch(
            "dns.asyncresolver.resolve",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError,
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await parse_uri("mongodb+srv://cluster.example.com/")


async def test_appname_utf8_length_limit() -> None:
    with pytest.raises(ValueError, match="128"):
        await parse_uri("mongodb://host/?appName=" + "я" * 65)


async def test_srv_txt_options_are_validated_before_host_limiting() -> None:
    with (
        patch(
            "dns.asyncresolver.resolve",
            new_callable=AsyncMock,
            side_effect=[
                srv_records("db1.example.com", "db2.example.com"),
                txt_records('"replicaSet=rs"'),
            ],
        ),
        pytest.raises(ValueError, match="srvMaxHosts"),
    ):
        await parse_uri("mongodb+srv://cluster.example.com/?srvMaxHosts=1")


async def test_srv_uri_overrides_txt_load_balancing() -> None:
    with patch(
        "dns.asyncresolver.resolve",
        new_callable=AsyncMock,
        side_effect=[
            srv_records("db1.example.com", "db2.example.com"),
            txt_records('"loadBalanced=true"'),
        ],
    ):
        parsed = await parse_uri(
            "mongodb+srv://cluster.example.com/?loadBalanced=false",
        )
    assert len(parsed.node_list) == 2
    assert parsed.options["loadBalanced"] is False


@pytest.mark.parametrize("port", [0, 65535])
async def test_srv_record_ports(port: int) -> None:
    record = dns.rdata.from_text("IN", "SRV", f"0 0 {port} db.example.com.")
    with patch(
        "dns.asyncresolver.resolve",
        new_callable=AsyncMock,
        side_effect=[[record], NoAnswer()],
    ):
        if port == 0:
            with pytest.raises(ValueError, match="Port"):
                await parse_uri("mongodb+srv://cluster.example.com/")
        else:
            parsed = await parse_uri("mongodb+srv://cluster.example.com/")
            assert parsed.node_list == [("db.example.com", port)]
