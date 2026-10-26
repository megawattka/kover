from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
import unittest
from unittest.mock import MagicMock, patch

from bson import Int64

from kover import (
    AuthCredentials,
    HelloResult,
    Kover,
    MongoTransport,
    WriteConcern,
)
from kover.network import ConnectionPool
from kover.session import Session
from kover.uri_parser import parse_uri

if TYPE_CHECKING:
    from kover.typings import JsonT


class ConnectionPoolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        patcher = patch("kover.network.pool.MongoTransport", autospec=True)
        self.transport_type = patcher.start()
        self.addCleanup(patcher.stop)
        self.connection = self.transport_type.return_value
        self.connection.is_connected = False
        self.connection.request.return_value = {"ok": 1.0}
        self.hello = MagicMock(spec=HelloResult)
        self.hello.requires_auth = False
        self.hello.is_primary = True
        self.connection.hello.return_value = self.hello

    @staticmethod
    async def test_session_assigns_increasing_transaction_numbers() -> None:
        session = Session({"id": "session"}, MagicMock())

        first = session.start_transaction()
        second = session.start_transaction()
        third = session.start_transaction()

        assert (first.tx_id, second.tx_id, third.tx_id) == (
            Int64(0), Int64(1), Int64(2),
        )

    async def test_lazy_initialization_and_reuse(self) -> None:
        credentials = AuthCredentials(username="user", password="password")
        loop = asyncio.get_running_loop()
        pool = ConnectionPool(
            "mongo",
            27018,
            credentials=credentials,
            loop=loop,
            compression=["zlib"],
            tls=True,
            application={"name": "test"},
            max_pool_size=1,
        )
        self.transport_type.assert_not_called()
        self.connection.connect.assert_not_awaited()

        assert await pool.request({"ping": 1}) == {"ok": 1.0}
        self.transport_type.assert_called_once_with(
            "mongo", 27018, loop=loop, tls=True)
        self.connection.connect.assert_awaited_once_with()
        self.connection.hello.assert_awaited_once_with(
            ["zlib"], credentials, {"name": "test"})
        self.connection.authorize.assert_not_awaited()

        self.connection.is_connected = True
        await pool.request({"ping": 1})
        self.connection.connect.assert_awaited_once_with()
        self.connection.hello.assert_awaited_once()
        await pool.close()

    async def test_authorization(self) -> None:
        credentials = AuthCredentials(username="user", password="password")
        self.hello.requires_auth = True
        self.hello.get_auth_mechanism.return_value = "SCRAM-SHA-256"
        pool = ConnectionPool(credentials=credentials, max_pool_size=1)

        await pool.request({"ping": 1})

        self.connection.authorize.assert_awaited_once_with(
            "SCRAM-SHA-256", credentials=credentials)
        await pool.close()

    async def test_request_options(self) -> None:
        pool = ConnectionPool(max_pool_size=1)
        transaction = MagicMock()
        document = {"ping": 1}

        response = await pool.request(
            document,
            db_name="test",
            transaction=transaction,
            wait_response=False,
        )

        assert response == {"ok": 1.0}
        self.connection.request.assert_awaited_once_with(
            document,
            db_name="test",
            transaction=transaction,
            wait_response=False,
        )
        await pool.close()

    async def test_request_failure_returns_connection(self) -> None:
        pool = ConnectionPool(max_pool_size=1)
        self.connection.request.side_effect = [RuntimeError("failed"), {}]
        self.connection.is_connected = True

        assert pool._connections.qsize() == 0  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access]
        with self.assertRaisesRegex(RuntimeError, "failed"):
            await pool.request({"ping": 1})

        assert pool._connections.qsize() == 0  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access]
        assert await pool.request({"ping": 1}) == {}
        assert pool._connections.qsize() == 1  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access]

        await pool.close()

    async def test_initialization_failure_replaces_connection(self) -> None:
        for stage in ("connect", "hello", "authorize"):
            with self.subTest(stage=stage):
                broken = MagicMock(spec=MongoTransport)
                replacement = MagicMock(spec=MongoTransport)
                broken.is_connected = False
                broken.hello.return_value = self.hello
                self.hello.requires_auth = True
                getattr(broken, stage).side_effect = RuntimeError("failed")
                replacement.is_connected = False
                replacement.hello.return_value = self.hello
                replacement.request.return_value = {"ok": 1.0}
                self.transport_type.side_effect = [broken, replacement]
                pool = ConnectionPool(max_pool_size=1)

                with self.assertRaisesRegex(RuntimeError, "failed"):
                    await pool.request({"ping": 1})

                broken.close.assert_awaited_once_with()
                assert await asyncio.wait_for(
                    pool.request({"ping": 1}), 1) == {"ok": 1.0}
                replacement.connect.assert_awaited_once_with()
                await pool.close()

    async def test_cancellation_returns_connection(self) -> None:
        pool = ConnectionPool(max_pool_size=1)
        started = asyncio.Event()
        blocked = asyncio.Event()

        async def request(*_args: object, **_kwargs: object) -> JsonT:
            started.set()
            await blocked.wait()
            return {}

        self.connection.request.side_effect = request
        task = asyncio.create_task(pool.request({"ping": 1}))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.connection.request.side_effect = None
        assert await asyncio.wait_for(
            pool.request({"ping": 1}), 1) == {"ok": 1.0}
        await pool.close()

    async def test_pool_creates_connections_lazily_and_respects_maximum(
        self,
    ) -> None:
        pool = ConnectionPool(max_pool_size=2)
        started = [asyncio.Event() for _ in range(3)]
        unblock = asyncio.Event()

        async def request(
            document: JsonT,
            **_kwargs: object,
        ) -> JsonT:
            request_id: int = document["request_id"]
            started[request_id].set()

            await unblock.wait()
            return {"ok": 1.0}

        connections = [
            MagicMock(spec=MongoTransport),
            MagicMock(spec=MongoTransport),
        ]

        for connection in connections:
            connection.is_connected = True
            connection.request.side_effect = request

        self.transport_type.side_effect = connections

        tasks: list[asyncio.Task[JsonT]] = []

        try:
            assert self.transport_type.call_count == 0

            tasks.extend(
                asyncio.create_task(
                    pool.request({"ping": 1, "request_id": index}),
                )
                for index in range(2)
            )

            await asyncio.wait_for(
                asyncio.gather(started[0].wait(), started[1].wait()),
                timeout=1,
            )

            tasks.append(
                asyncio.create_task(
                    pool.request({"ping": 1, "request_id": 2}),
                ),
            )

            # Give the third task an opportunity to attempt acquisition.
            await asyncio.sleep(0)

            assert self.transport_type.call_count == 2
            assert not started[2].is_set()

            unblock.set()

            await asyncio.wait_for(
                asyncio.gather(*tasks),
                timeout=1,
            )

            assert started[2].is_set()
            assert self.transport_type.call_count == 2
            assert pool._connections.qsize() == 2  # pyright: ignore[reportPrivateUsage] # ruff: ignore[private-member-access]

        finally:
            unblock.set()

            for task in tasks:
                if not task.done():
                    task.cancel()

            await asyncio.gather(*tasks, return_exceptions=True)
            await pool.close()

    async def test_close_all_connections_once(self) -> None:
        connections = [MagicMock(spec=MongoTransport) for _ in range(3)]
        for connection in connections:
            async def request(_command: JsonT, **_kwargs: object) -> JsonT:
                await asyncio.sleep(0.5)
                return {"ok": 1.0}

            connection.is_connected = True
            connection.request = request

        self.transport_type.side_effect = connections
        pool = ConnectionPool(max_pool_size=3)

        await asyncio.gather(*[
            pool.request({"ping": 1}) for _ in range(3)
        ])
        await pool.close()

        for connection in connections:
            connection.close.assert_awaited_once_with()

    async def test_uri_primary_discovery(self) -> None:
        parsed = await parse_uri(
            "mongodb://user:password@seed:27017/"
            "?tls=true&maxPoolSize=2&compressors=zlib&appName=test")
        self.hello.is_primary = False
        self.hello.primary_node = "primary:27018"

        pool = await ConnectionPool.from_parsed_uri(parsed)

        assert self.transport_type.call_count == 1
        assert self.transport_type.call_args_list[0].args == ("seed", 27017)
        self.connection.hello.assert_awaited_once_with(
            ["zlib"], parsed.credentials, {"name": "test"})
        self.connection.close.assert_awaited_once_with()

        await pool.request({"ping": 1})

        self.transport_type.assert_called_with(
            "primary", 27018, loop=None, tls=True)
        self.connection.hello.assert_awaited_with(
            ["zlib"], parsed.credentials, {"name": "test"})
        await pool.close()

    async def test_uri_primary_uses_seed(self) -> None:
        parsed = await parse_uri("mongodb://seed:27018/?maxPoolSize=1")

        pool = await ConnectionPool.from_parsed_uri(parsed)

        assert self.transport_type.call_count == 1
        self.transport_type.assert_called_with(
            "seed", 27018, loop=None, tls=False)
        await pool.close()

    async def test_discovery_failure_closes_transport(self) -> None:
        parsed = await parse_uri("mongodb://seed:27017/")
        self.connection.hello.side_effect = RuntimeError("failed")

        with self.assertRaisesRegex(RuntimeError, "failed"):
            await ConnectionPool.from_parsed_uri(parsed)

        self.connection.close.assert_awaited_once_with()
        self.transport_type.assert_called_once()


class ClientPoolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        patcher = patch("kover.client.ConnectionPool", autospec=True)
        self.pool_type = patcher.start()
        self.addCleanup(patcher.stop)
        self.pool = self.pool_type.return_value

    async def test_client_delegates_requests_and_close(self) -> None:
        client = Kover(pool=self.pool)
        transaction = MagicMock(is_active=False)
        self.pool.request.return_value = {"ok": 1.0}

        response = await client.request(
            {"ping": 1},
            db_name="test",
            transaction=transaction,
            wait_response=False,
        )
        await client.close()

        assert response == {"ok": 1.0}
        self.pool.request.assert_awaited_once_with(
            {"ping": 1},
            db_name="test",
            transaction=transaction,
            wait_response=False,
        )
        self.pool.close.assert_awaited_once_with()

    async def test_write_concern_only_to_supported_commands(self) -> None:
        client = Kover(pool=self.pool)
        await client.request({"ping": 1})
        await client.request({"insert": "items"})

        assert self.pool.request.await_args_list[0].args[0] == {"ping": 1}
        assert self.pool.request.await_args_list[1].args[0] == {
            "insert": "items",
            "writeConcern": {"w": "majority"},
        }

    async def test_write_concern_operation_override_and_command_field_win(
        self,
    ) -> None:
        client = Kover(pool=self.pool)
        override = WriteConcern(w=2, j=True)
        await client.request({"update": "items"}, write_concern=override)
        await client.request({
            "delete": "items", "writeConcern": {"w": 3},
        }, write_concern=override)

        assert (
            self.pool.request.await_args_list[0].args[0]["writeConcern"]
            == {
                "w": 2,
                "j": True,
            }
        )
        assert (
            self.pool.request.await_args_list[1].args[0]["writeConcern"]
            == {
                "w": 3,
            }
        )

    async def test_transaction_suppresses_default_write_concern(self) -> None:
        client = Kover(pool=self.pool)
        transaction = MagicMock(is_active=True)
        await client.request({"insert": "items"}, transaction=transaction)

        assert "writeConcern" not in self.pool.request.await_args.args[0]

    async def test_uri_parses_write_concern_options(self) -> None:
        uri = "mongodb://seed:27017/?w=2&journal=true&wtimeoutMS=4000"
        self.pool_type.from_parsed_uri.return_value = self.pool

        client = await Kover.from_uri(uri)

        await client.request({"insert": "items"})
        assert self.pool.request.await_args.args[0]["writeConcern"] == {
            "w": 2,
            "j": True,
            "wtimeout": 4000,
        }

    async def test_uri_options_are_used_as_client_default(self) -> None:
        uri = "mongodb://seed:27017/?w=2&journal=true&wtimeoutMS=4000"
        self.pool_type.from_parsed_uri.return_value = self.pool

        client = await Kover.from_uri(uri)
        await client.request({"insert": "items"})

        assert self.pool.request.await_args.args[0]["writeConcern"] == {
            "w": 2,
            "j": True,
            "wtimeout": 4000,
        }

    async def test_make_client_passes_configuration_to_pool(self) -> None:
        credentials = AuthCredentials(username="user", password="password")
        loop = asyncio.get_running_loop()

        client = await Kover.make_client(
            "mongo",
            27018,
            credentials=credentials,
            loop=loop,
            compression=["zlib"],
            tls=True,
            application={"name": "test"},
            w=1,
            max_pool_size=5,
        )

        self.pool_type.assert_called_once_with(
            "mongo",
            27018,
            credentials=credentials,
            loop=loop,
            compression=["zlib"],
            tls=True,
            application={"name": "test"},
            max_pool_size=5,
        )
        assert "WriteConcern(w=1," in repr(client)
        assert "_credentials" not in vars(client)
        assert "_compression" not in vars(client)
        assert "_application" not in vars(client)
        await client.close()

    async def test_from_uri_delegates_discovery(self) -> None:
        uri = "mongodb://seed:27017/?w=1&maxPoolSize=5"
        parsed = await parse_uri(uri)
        loop = asyncio.get_running_loop()
        self.pool_type.from_parsed_uri.return_value = self.pool

        client = await Kover.from_uri(uri, loop=loop)

        self.pool_type.from_parsed_uri.assert_awaited_once_with(
            parsed, loop=loop)
        assert "WriteConcern(w=1," in repr(client)
        await client.close()
        self.pool.close.assert_awaited_once_with()
