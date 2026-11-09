from __future__ import annotations

import asyncio
from unittest.mock import patch

import dns.asyncresolver
import dns.message
import dns.rdatatype
import dns.rrset

from kover.network.uri_parser import parse_uri


class MongoDnsServer(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.transport: asyncio.DatagramTransport | None = None
        self.queries: list[tuple[str, int]] = []

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        assert isinstance(transport, asyncio.DatagramTransport)
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        request = dns.message.from_wire(data)
        question = request.question[0]
        self.queries.append((question.name.to_text(), question.rdtype))
        response = dns.message.make_response(request)
        if question.rdtype == dns.rdatatype.SRV:
            values = (
                "0 0 27018 db1.example.test.",
                "0 0 27019 db2.example.test.",
            )
        else:
            values = ('"authSource=users&replicaSet=rs"',)
        response.answer.append(
            dns.rrset.from_text(
                question.name,
                60,
                "IN",
                question.rdtype,
                *values,
            ),
        )
        assert self.transport is not None
        self.transport.sendto(response.to_wire(), addr)


async def test_uri_discovery_with_real_async_dns_resolver() -> None:
    loop = asyncio.get_running_loop()
    transport, server = await loop.create_datagram_endpoint(
        MongoDnsServer,
        local_addr=("127.0.0.1", 0),
    )
    resolver = dns.asyncresolver.Resolver(configure=False)
    resolver.nameservers = ["127.0.0.1"]
    resolver.port = transport.get_extra_info("sockname")[1]
    try:
        with patch(
            "dns.asyncresolver.get_default_resolver",
            return_value=resolver,
        ):
            async with asyncio.timeout(5):
                parsed = await parse_uri(
                    "mongodb+srv://user:secret@cluster.example.test/shop"
                    "?connectTimeoutMS=1000&appName=dns-test",
                )
        assert set(parsed.node_list) == {
            ("db1.example.test", 27018),
            ("db2.example.test", 27019),
        }
        assert parsed.fqdn == "cluster.example.test"
        assert parsed.options["tls"] is True
        assert parsed.options["replicaSet"] == "rs"
        assert parsed.options["appname"] == "dns-test"
        assert parsed.credentials is not None
        assert parsed.credentials.auth_database == "users"
        assert server.queries == [
            ("_mongodb._tcp.cluster.example.test.", dns.rdatatype.SRV),
            ("cluster.example.test.", dns.rdatatype.TXT),
        ]
    finally:
        transport.close()
