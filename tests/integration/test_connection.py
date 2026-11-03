import asyncio
import os
from urllib.parse import quote

from kover import AuthCredentials, Kover
from tests.integration.base import MongoTestCase


class ConnectionIntegrationTests(MongoTestCase):
    async def test_concurrent_connections_are_authenticated_and_bounded(
        self,
    ) -> None:
        credentials = AuthCredentials.from_environ()
        client = await Kover.make_client(
            host=os.environ.get("MONGO_HOST", "127.0.0.1"),
            port=int(os.environ.get("MONGO_PORT", "27017")),
            credentials=credentials,
            max_pool_size=2,
        )
        self.addAsyncCleanup(client.close)
        statuses = await asyncio.gather(*(
            client.request({"connectionStatus": 1}) for _ in range(12)
        ))
        if credentials is not None:
            for status in statuses:
                assert {
                    "user": credentials.username,
                    "db": credentials.auth_database,
                } in status["authInfo"]["authenticatedUsers"]
        stats = client.pool.stats()
        assert 1 <= stats.idle <= 2
        assert stats.checked_out == 0
        await client.close()
        assert client.pool.closed
        assert client.pool.stats().idle == 0

    async def test_client_context_propagates_exception_and_closes(
        self,
    ) -> None:
        client = await Kover.make_client(
            host=os.environ.get("MONGO_HOST", "127.0.0.1"),
            port=int(os.environ.get("MONGO_PORT", "27017")),
            credentials=AuthCredentials.from_environ(),
        )
        self.addAsyncCleanup(client.close)
        with self.assertRaisesRegex(ValueError, "body failed"):
            async with client:
                assert await client.get_database("admin").ping()
                raise ValueError("body failed")
        assert client.pool.closed
        assert client.pool.stats().idle == 0

    async def test_uri_and_zlib_roundtrip(self) -> None:
        credentials = AuthCredentials.from_environ()
        auth = ""
        if credentials is not None:
            auth = (
                quote(credentials.username, safe="") + ":"
                + quote(credentials.password, safe="") + "@"
            )
        host = os.environ.get("MONGO_HOST", "127.0.0.1")
        if ":" in host:
            host = f"[{host}]"
        auth_db = quote(os.environ.get("MONGO_AUTH_DB", "admin"), safe="")
        uri = (
            f"mongodb://{auth}{host}:{os.environ.get('MONGO_PORT', '27017')}/"
            f"?compressors=zlib&authSource={auth_db}"
        )
        client = await Kover.from_uri(uri)
        self.addAsyncCleanup(client.close)
        collection = client.get_database(self.database.name).get_collection(
            "compressed",
        )
        text = "compressible" * 10000
        identifier = await collection.insert_one({"text": text})
        stored = await collection.find_one({"_id": identifier})
        assert isinstance(stored, dict)
        assert stored["text"] == text
