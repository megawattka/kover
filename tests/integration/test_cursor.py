from kover.exceptions import OperationFailure
from kover.models.tx_state import TxnState
from tests.integration.base import MongoTestCase


class CursorIntegrationTests(MongoTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.collection = await self.database.create_collection("items")
        await self.collection.insert_many(
            [{"value": value} for value in range(37)],
        )

    async def test_multiple_batches_and_early_close(self) -> None:
        cursor = self.collection.find().sort({"value": 1}).batch_size(2)
        assert (await anext(cursor))["value"] == 0
        assert [doc["value"] for doc in await cursor.to_list()] == list(
            range(1, 37),
        )
        await cursor.close()
        async with self.collection.find().batch_size(2) as cursor:
            await anext(cursor)
        with self.assertRaises(StopAsyncIteration):
            await anext(cursor)
        assert await self.database.ping()

    async def test_listing_and_empty_result(self) -> None:
        names = await self.database.list_collections(name_only=True)
        assert names == ["items"]
        indexes = await self.collection.list_indexes()
        assert [index.name for index in indexes] == ["_id_"]
        assert await self.collection.find({"value": -1}).to_list() == []


class SessionIntegrationTests(MongoTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        hello = await self.client.command({"hello": 1})
        if not hello.get("setName"):
            self.skipTest("Transactions require a replica set")

        self.collection = await self.database.create_collection("items")
        self.session = await self.client.start_session()
        self.addAsyncCleanup(self.client.end_sessions, [self.session])
        self.addAsyncCleanup(self.session.close)

    async def test_commit_with_session_cursor(self) -> None:
        self.session.start_transaction()
        await self.collection.insert_many(
            [{"value": value} for value in range(9)],
            session=self.session,
        )
        async with (
            self.collection.find(
                session=self.session,
            )
            .sort({"value": 1})
            .batch_size(2) as cursor
        ):
            assert [doc["value"] for doc in await cursor.to_list()] == list(
                range(9),
            )
        await self.session.commit_transaction()
        assert self.session.state is TxnState.COMMITTED
        assert await self.collection.count() == 9

    async def test_empty_transactions_finish_and_session_can_be_reused(
        self,
    ) -> None:
        self.session.start_transaction()
        await self.session.commit_transaction()
        await self.session.commit_transaction()
        assert self.session.state is TxnState.COMMITTED

        self.session.start_transaction()
        await self.session.abort_transaction()
        assert self.session.state is TxnState.ABORTED

        self.session.start_transaction()
        await self.collection.insert_one({"value": 1}, session=self.session)
        await self.session.commit_transaction()
        assert await self.collection.count() == 1

    async def test_abort_and_reuse_session(self) -> None:
        self.session.start_transaction()
        await self.collection.insert_one({"value": 1}, session=self.session)
        await self.session.abort_transaction()
        assert self.session.state is TxnState.ABORTED
        assert await self.collection.find_one() is None
        self.session.start_transaction()
        await self.collection.insert_one({"value": 2}, session=self.session)
        await self.session.commit_transaction()
        assert await self.collection.count({"value": 2}) == 1

    async def test_duplicate_key_rolls_back_transaction(self) -> None:
        self.session.start_transaction()
        document = {"_id": "duplicate"}
        await self.collection.insert_one(document, session=self.session)
        with self.assertRaises(OperationFailure) as caught:
            await self.collection.insert_one(document, session=self.session)
        assert caught.exception.code == 11000
        await self.session.abort_transaction()
        assert self.session.state is TxnState.ABORTED
        assert await self.collection.count() == 0
