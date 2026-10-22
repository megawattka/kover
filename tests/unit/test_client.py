import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from kover.client import Kover
from kover.exceptions import OperationFailure
from kover.network.auth import AuthCredentials
from kover.network.pool import ConnectionPool
from kover.network.transport import MongoTransport
from kover.session import Session


class ClientTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def socket(mechanisms: list[str] | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            hello=AsyncMock(
                return_value=SimpleNamespace(mechanisms=mechanisms),
            ),
            close=AsyncMock(),
            request=AsyncMock(),
            hello_result=None,
            writer=Mock(is_closing=Mock(return_value=False)),
        )

    async def test_auth_always_attempted_and_mechanism_deterministic(
        self,
    ) -> None:
        credentials = AuthCredentials(username="user", password="password")
        for mechanisms, expected in (
            (None, "SCRAM-SHA-256"),
            ([], "SCRAM-SHA-256"),
            (["SCRAM-SHA-1"], "SCRAM-SHA-1"),
            (["SCRAM-SHA-1", "SCRAM-SHA-256"], "SCRAM-SHA-256"),
        ):
            connection = MagicMock(spec=MongoTransport)
            connection.is_connected = False
            connection.request.return_value = {"ok": 1.0}
            hello = MagicMock()
            hello.requires_auth = True
            hello.get_auth_mechanism.return_value = expected
            connection.hello.return_value = hello
            with (
                self.subTest(mechanisms=mechanisms),
                patch.object(
                    ConnectionPool, "_create_connection",
                    return_value=connection,
                ),
            ):
                pool = ConnectionPool(credentials=credentials, max_pool_size=1)
                await pool.request({"ping": 1})
                hello.get_auth_mechanism.assert_called_once_with()
                connection.authorize.assert_awaited_once_with(
                    expected, credentials=credentials,
                )
                await pool.close()

    @staticmethod
    async def test_no_credentials_no_authentication() -> None:
        connection = MagicMock(spec=MongoTransport)
        connection.is_connected = False
        connection.request.return_value = {"ok": 1.0}
        hello = MagicMock()
        hello.requires_auth = True
        connection.hello.return_value = hello
        with (
            patch.object(
                ConnectionPool, "_create_connection", return_value=connection,
            ),
        ):
            pool = ConnectionPool(max_pool_size=1)
            assert await pool.request({"ping": 1}) == {"ok": 1.0}
            connection.hello.assert_awaited_once_with(None, None, None)
            connection.authorize.assert_awaited_once_with(
                hello.get_auth_mechanism.return_value,
                credentials=None,
            )
            await pool.close()

    async def test_constructor_failure_closes_socket(self) -> None:
        class BrokenClient(Kover):
            def __init__(self, **_kwargs: object) -> None:
                raise RuntimeError("constructor")

        with self.assertRaisesRegex(RuntimeError, "constructor"):
            await BrokenClient.make_client()

    async def test_initialization_cancellation_closes_connection(self) -> None:
        connection = MagicMock(spec=MongoTransport)
        connection.is_connected = False
        entered = asyncio.Event()

        async def hello(*_args: object) -> None:
            entered.set()
            await asyncio.Event().wait()

        connection.hello.side_effect = hello
        with patch.object(
            ConnectionPool, "_create_connection", return_value=connection,
        ):
            pool = ConnectionPool(max_pool_size=1)
            task = asyncio.create_task(pool.request({"ping": 1}))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            connection.close.assert_awaited_once_with()
            await pool.close()

    async def test_cancelled_authentication_closes_connection(self) -> None:
        connection = MagicMock(spec=MongoTransport)
        connection.is_connected = False
        hello = MagicMock()
        hello.requires_auth = True
        hello.get_auth_mechanism.return_value = "SCRAM-SHA-256"
        connection.hello.return_value = hello
        connection.authorize.side_effect = asyncio.CancelledError
        credentials = AuthCredentials(username="u", password="p")
        with patch.object(
            ConnectionPool, "_create_connection", return_value=connection,
        ):
            pool = ConnectionPool(credentials=credentials, max_pool_size=1)
            with self.assertRaises(asyncio.CancelledError):
                await pool.request({"ping": 1})
            connection.authorize.assert_awaited_once_with(
                "SCRAM-SHA-256", credentials=credentials,
            )
            connection.close.assert_awaited_once_with()
            await pool.close()

    @staticmethod
    async def test_shutdown_sends_command_without_waiting() -> None:
        socket = MagicMock(spec=MongoTransport)
        socket.is_connected = False
        socket.connect.return_value = None
        socket.hello.return_value.requires_auth = False
        socket.request.return_value = {}
        pool = ConnectionPool(max_pool_size=1)
        pool._create_connection = Mock(return_value=socket)  # pyright: ignore[reportPrivateUsage] # ruff: ignore[private-member-access]
        client = Kover(pool=pool)

        await client.shutdown()

        socket.request.assert_awaited_once_with(
            {"shutdown": 1.0, "force": False}, db_name="admin",
            transaction=None, wait_response=False,
        )
        socket.close.assert_awaited_once_with()

    @staticmethod
    async def test_session_capability_checked() -> None:
        pool = AsyncMock(spec=ConnectionPool)
        client = Kover(pool=pool)

        session = await client.start_session()

        pool.request.assert_awaited_once_with(
            {"startSession": 1.0},
            db_name="admin",
            transaction=None,
            wait_response=True,
        )
        assert session.client is client

    async def test_command_error_keeps_socket(self) -> None:
        connection = MagicMock(spec=MongoTransport)
        connection.is_connected = False
        connection.hello.return_value.requires_auth = False
        connection.request.side_effect = OperationFailure(13, {
            "message": "denied",
        })
        pool = ConnectionPool(max_pool_size=1)
        with patch.object(
            ConnectionPool, "_create_connection", return_value=connection,
        ):
            client = Kover(pool=pool)
            self.addAsyncCleanup(client.close)
            with self.assertRaises(OperationFailure):
                await client.request({"ping": 1})
            connection.close.assert_awaited_once_with()

            connection.is_connected = False
            connection.request.side_effect = None
            connection.request.return_value = {"ok": 1}
            assert await client.request({"ping": 1}) == {"ok": 1}
            assert connection.request.await_count == 2

    async def test_session_lifecycle_rejects_foreign_client(self) -> None:
        connection = MagicMock(spec=MongoTransport)
        connection.is_connected = False
        connection.hello.return_value.requires_auth = False
        connection.request.return_value = {"ok": 1.0}
        pool = ConnectionPool(max_pool_size=1)
        with patch.object(
            ConnectionPool, "_create_connection", return_value=connection,
        ):
            client = Kover(pool=pool)
            self.addAsyncCleanup(client.close)
            foreign = Session({"id": "other"}, Kover(pool=AsyncMock()))
            for method in (client.refresh_sessions, client.end_sessions):
                with self.assertRaisesRegex(ValueError, "foreign session"):
                    await method([foreign])
            connection.request.assert_not_awaited()
            session = Session({"id": "ours"}, client)
            await client.refresh_sessions([session])
            await client.end_sessions([session])
            assert connection.request.await_count == 2


if __name__ == "__main__":
    unittest.main()
