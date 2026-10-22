"""Opt-in tests. Only databases named kover_test_<uuid> are removed.

Run from the repository root:
KOVER_RUN_INTEGRATION=1 python -m unittest discover -s tests/integration -v
Credentials: MONGO_USER, MONGO_PASSWORD, optional MONGO_AUTH_DB (admin).
"""

import os
from typing import TYPE_CHECKING
import unittest
from unittest.mock import AsyncMock

from kover import AuthCredentials, Document, Kover, OperationFailure
from kover.transaction import TxnState
from tests.integration.base import MongoTestCase

if TYPE_CHECKING:
    from bson import Int64

    from kover.cursor import Cursor
    from kover.session import Session
    from kover.typings import JsonT


class Item(Document):
    value: int


class CursorIntegrationTests(MongoTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.collection = await self.database.create_collection("items")
        await self.collection.insert_many([{"value": n} for n in range(37)])

    async def new_session(self) -> "Session":
        hello = await self.client.request({"hello": 1})
        if not hello.get("setName"):
            self.skipTest("Transaction tests require a replica set")
        session = await self.client.start_session()
        self.addAsyncCleanup(self.client.end_sessions, [session])
        return session

    async def test_transaction_and_cursor_move_between_pooled_sockets(
        self,
    ) -> None:
        session = await self.new_session()
        async with session.start_transaction() as transaction:
            cursor = self.collection.find(
                transaction=transaction,
            ).batch_size(2)
            async with cursor:
                await anext(cursor)
                await anext(cursor)
                await anext(cursor)  # getMore on another socket.
                assert self.client._pool._connections.qsize() == 1  # pyright: ignore[reportPrivateUsage] # ruff: ignore[private-member-access]

        assert transaction.state == TxnState.COMMITTED

    async def test_find_many_batches_and_models(self) -> None:
        cursor = self.collection.find(cls=Item).sort({"value": 1})
        cursor.batch_size(3)
        items = await cursor.to_list()
        assert [item.value for item in items] == list(range(37))
        assert await cursor.to_list() == []

    async def test_limit_skip_projection(self) -> None:
        items = await self.collection.find().sort({"value": 1}).skip(4).limit(
            8,
        ).batch_size(2).projection({"_id": 0, "value": 1}).to_list()
        assert items == [{"value": n} for n in range(4, 12)]

    async def test_zero_initial_batch(self) -> None:
        items = await self.collection.find().batch_size(0).to_list()
        assert len(items) == 37

    async def test_early_close_removes_server_cursor(self) -> None:
        original = self.database.command
        self.database.command = AsyncMock(wraps=original)
        async with self.collection.find().batch_size(2) as cursor:
            await anext(cursor)
        calls = self.database.command.await_args_list
        kill = calls[-1].args[0]
        assert kill["killCursors"] == "items"
        cursor_id = kill["cursors"][0]
        with self.assertRaises(OperationFailure) as caught:
            await original({"getMore": cursor_id, "collection": "items"})
        assert caught.exception.code == 43
        assert await cursor.to_list() == []

    async def test_aggregate_reads_many_batches(self) -> None:
        items = await self.collection.aggregate([
            {"$sort": {"value": 1}}, {"$project": {"_id": 0, "value": 1}},
        ], cursor={"batchSize": 2}).to_list()
        assert items == [{"value": n} for n in range(37)]

    async def test_write_and_read_batch_larger_than_one_bson_document(
        self,
    ) -> None:
        payload = "x" * (9 * 1024 * 1024)
        await self.collection.insert_many([
            {"large": True, "payload": payload},
            {"large": True, "payload": payload},
        ])
        cursor: Cursor[JsonT] = self.collection.find({
            "large": True,
        }).batch_size(2)
        async with cursor:
            documents = await cursor.to_list()
        assert len(documents) == 2
        assert all(len(d["payload"]) == len(payload) for d in documents)

    async def test_transaction_cursor_and_sequential_commits(self) -> None:
        session = await self.new_session()
        numbers: list[Int64] = []
        for value in (100, 101):
            async with session.start_transaction() as transaction:
                numbers.append(transaction.tx_id)
                await self.collection.insert_one({"value": value},
                                                 transaction=transaction)
                items = await self.collection.find(
                    {"value": {"$gte": 0}}, cls=None, transaction=transaction,
                ).batch_size(2).to_list()
                assert value in [item["value"] for item in items]
                aggregated = await self.collection.aggregate(
                    [{"$match": {"value": value}}],
                    cursor={"batchSize": 0}, transaction=transaction,
                ).to_list()
                assert len(aggregated) == 1
            assert transaction.state == TxnState.COMMITTED
        assert numbers[1] > numbers[0]
        assert await self.collection.count() == 39

    async def test_body_exception_aborts_and_propagates(self) -> None:
        session = await self.new_session()
        transaction = session.start_transaction()
        with self.assertRaisesRegex(ValueError, "rollback"):
            async with transaction:
                await self.collection.insert_one({"value": 100},
                                                 transaction=transaction)
                async with self.collection.find(
                    transaction=transaction,
                ).batch_size(2) as cursor:
                    await anext(cursor)
                    raise ValueError("rollback")
        assert transaction.state == TxnState.ABORTED
        assert await self.collection.count() == 37

    async def test_duplicate_key_aborts_and_preserves_server_error(
        self,
    ) -> None:
        session = await self.new_session()
        transaction = session.start_transaction()
        with self.assertRaises(OperationFailure) as caught:
            async with transaction:
                await self.collection.insert_one({
                    "_id": "duplicate", "value": 1,
                }, transaction=transaction)
                await self.collection.insert_one({
                    "_id": "duplicate", "value": 2,
                }, transaction=transaction)
        assert caught.exception.code == 11000
        assert transaction.state == TxnState.ABORTED
        assert transaction.exception is caught.exception
        assert await self.collection.count() == 37

    async def test_collection_and_index_listing(self) -> None:
        names = await self.database.list_collections(name_only=True)
        assert names == ["items"]
        indexes = await self.collection.list_indexes()
        assert [index.name for index in indexes] == ["_id_"]

    async def test_empty_result_and_explain(self) -> None:
        assert await self.collection.find({
            "value": -1,
        }).batch_size(2).to_list() == []
        explanation = await self.collection.aggregate(
            [],
            explain=True,
        ).to_list()
        assert len(explanation) == 1
        assert "queryPlanner" in explanation[0]

    async def test_explicit_abort_and_commit(self) -> None:
        session = await self.new_session()
        async with session.start_transaction() as transaction:
            await self.collection.insert_one({"value": 100},
                                             transaction=transaction)
            await transaction.abort()
            assert transaction.state == TxnState.ABORTED

        assert await self.collection.count() == 37
        async with session.start_transaction() as transaction:
            await self.collection.insert_one({"value": 101},
                                             transaction=transaction)
            await transaction.commit()
            assert transaction.state == TxnState.COMMITTED
        assert await self.collection.count() == 38

    async def test_client_context_propagates_and_closes(self) -> None:
        credentials = AuthCredentials.from_environ()
        client = await Kover.make_client(
            host=os.environ.get("MONGO_HOST", "127.0.0.1"),
            port=int(os.environ.get("MONGO_PORT", "27017")),
            credentials=credentials,
        )
        self.addAsyncCleanup(client.close)
        with self.assertRaisesRegex(ValueError, "body"):
            async with client:
                assert await client.get_database("admin").ping()
                raise ValueError("body")

        assert client.pool.closed
        assert client._pool._connections.qsize() == 0  # pyright: ignore[reportPrivateUsage] # ruff: ignore[private-member-access]


if __name__ == "__main__":
    unittest.main()
