"""Opt-in connection/auth tests; no destructive or shutdown commands."""
from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any, TypedDict, Unpack
import unittest
from unittest.mock import patch

from kover import AuthCredentials, Kover
from kover.network.transport import MongoTransport

if TYPE_CHECKING:
    from kover.transaction import Transaction


class Options(TypedDict):
    host: str
    port: int


class RequestKwargs(TypedDict):
    db_name: str
    transaction: Transaction | None
    wait_response: bool


class ConnectionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def options() -> Options:
        return {
            "host": os.environ.get("MONGO_HOST", "127.0.0.1"),
            "port": int(os.environ.get("MONGO_PORT", "27017")),
        }

    async def test_factory_finishes_hs_and_auth_before_returning(self) -> None:
        credentials = AuthCredentials.from_environ()
        client = await Kover.make_client(
            **self.options(), credentials=credentials,
        )
        async with client:
            assert await client.get_database("admin").ping()

        assert client._pool.closed  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access]
        assert client._pool._connections.qsize() == 0  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access]

    async def test_multiple_conns_authenticated_and_bounded(self) -> None:
        credentials = AuthCredentials.from_environ()
        async with await Kover.make_client(
            **self.options(), credentials=credentials,
            max_pool_size=3,
        ) as client:
            pool = client._pool  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access]
            assert pool._connections.qsize() == 0  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access]

            statuses: list[dict[str, Any]] = []
            original_request = MongoTransport.request

            async def observe_request(
                connection: MongoTransport,
                doc: dict[str, Any],
                **kwargs: Unpack[RequestKwargs],
            ) -> dict[str, Any]:
                response = await original_request(connection, doc, **kwargs)
                if doc.get("connectionStatus"):
                    statuses.append(response)
                await asyncio.sleep(0.01)
                return response

            with patch.object(MongoTransport, "request", observe_request):
                await asyncio.gather(*(
                    pool.request({"connectionStatus": 1}) for _ in range(3)
                ))

            assert len(statuses) == 3
            assert pool._connections.qsize() == 3  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access]
            assert pool._connection_count == 3  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access]
            if credentials is not None:
                assert all(
                    status["authInfo"]["authenticatedUsers"]
                    for status in statuses
                )

            assert all(await asyncio.gather(*(
                client.get_database("admin").ping() for _ in range(12)
            )))

            await pool.close()
            assert pool._connections.qsize() == 0  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access]
