import os
from urllib.parse import quote

from kover import (
    AuthCredentials,
    BulkWriteBuilder,
    Delete,
    Kover,
    OperationFailure,
    Update,
)
from kover.gridfs import GridFS
from kover.network import WireHelper
from tests.integration.base import MongoTestCase


class UpstreamFeatureTests(MongoTestCase):
    async def test_bulk_sequences_exceed_one_bson_document(self) -> None:
        builder = BulkWriteBuilder()
        builder.add_insert([
            {"text": "x" * (9 * 1024 * 1024)},
            {"text": "y" * (9 * 1024 * 1024)},
        ], ns=f"{self.database.name}.large_bulk")

        reply = await self.client.bulk_write(builder.build()).to_list()
        assert len(reply) == 2
        assert await self.database.large_bulk.count() == 2

    async def test_uri_and_zlib_roundtrip(self) -> None:
        credentials = AuthCredentials.from_environ()
        auth = ""
        if credentials is not None:
            auth = (quote(credentials.username, safe="") + ":" +
                    quote(credentials.password, safe="") + "@")
        host = os.environ.get("MONGO_HOST", "127.0.0.1")
        if ":" in host:
            host = f"[{host}]"
        uri = (
            f"mongodb://{auth}{host}:{os.environ.get('MONGO_PORT', '27017')}/"
            f"{self.database.name}?compressors=zlib&appName=kover-test&"
            f"authSource={quote(os.environ.get('MONGO_AUTH_DB', 'admin'))}"
        )
        client = await Kover.from_uri(uri)
        self.addAsyncCleanup(client.close)
        collection = client.get_database(self.database.name).compressed
        text = "compressible" * 10000
        identifier = await collection.insert_one({"text": text})
        found = await collection.find_one({"_id": identifier})
        if found is None:
            self.fail("Compressed document was not found")
        assert found["text"] == text

    async def test_bulk_multiple_result_batches_and_errors(self) -> None:
        namespace = f"{self.database.name}.bulk"
        builder = BulkWriteBuilder(cursor_batch_size=1)
        builder.add_insert([{"value": n} for n in range(4)], ns=namespace)
        builder.add_update(Update({"value": 10}, {"$set": {"new": True}},
                                  upsert=True), namespace)
        builder.add_delete(Delete({"value": 0}, limit=1), namespace)
        reply = await self.client.bulk_write(builder.build()).to_list()
        assert len(reply) == 6
        assert await self.database.bulk.count() == 4
        found = await self.database.bulk.find_one({"value": 10})
        if found is None:
            self.fail("Upserted document was not found")
        assert found["new"]
        builder = BulkWriteBuilder(ordered=False, cursor_batch_size=1)
        builder.add_insert([{"_id": "duplicate"}, {"_id": "duplicate"},
                            {"_id": "after"}], ns=namespace)

        helper = WireHelper()
        with self.assertRaises(OperationFailure) as caught:
            reply = await self.client.bulk_write(builder.build()).to_list()
            for op in reply:
                if op["ok"] == 0:
                    exc = await helper.get_exception(op)
                    raise exc

        assert caught.exception.code == 11000
        assert len(reply) == 3
        assert await self.database.bulk.find_one({"_id": "after"}) is not None

    async def test_empty_gridfs_and_invalid_chunk_sizes(self) -> None:
        fs = await GridFS(self.database).indexed()
        identifier = await fs.put(b"")
        file, stream = await fs.get_by_file_id(identifier)

        assert file.length == 0
        assert stream.read() == b""
        assert await self.database.fs.chunks.count() == 0
        for size in (0, -1, True, 16 * 1024 * 1024):
            with self.assertRaises(ValueError):
                await fs.put(b"data", chunk_size=size)
