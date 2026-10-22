"""Concurrent read/write workloads against an opt-in real MongoDB.

Run with KOVER_RUN_INTEGRATION=1; connection settings come from MONGO_HOST,
MONGO_PORT, MONGO_USER and MONGO_PASSWORD. Each test uses an isolated database.
"""

import asyncio
from collections.abc import Coroutine
import os
import unittest

from kover import AuthCredentials, Delete, Kover, Update
from tests.integration.base import MongoTestCase


class MultipleWorkersIntegrationTests(MongoTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        # Many more tasks than connections exercise pool waiting and reuse.
        client = await Kover.make_client(
            host=os.environ.get("MONGO_HOST", "127.0.0.1"),
            port=int(os.environ.get("MONGO_PORT", "27017")),
            credentials=AuthCredentials.from_environ(),
            max_pool_size=4,
        )
        self.addAsyncCleanup(client.close)
        self.database = client.get_database(self.database.name)

    @staticmethod
    async def run_workers(
        start: asyncio.Event,
        workers: list[Coroutine[None, None, None]],
    ) -> None:
        """Start together, bound runtime, and join all tasks before cleanup."""
        tasks = [asyncio.create_task(worker) for worker in workers]
        try:
            await asyncio.sleep(0)
            start.set()
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=90)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_parallel_workers_with_independent_documents(self) -> None:
        collection = await self.database.create_collection("independent")
        worker_count, rounds, batch_size = 24, 3, 32
        start = asyncio.Event()

        async def worker(worker_id: int) -> None:
            await start.wait()
            payload = f"{worker_id:04d}" * 512
            for round_id in range(rounds):
                selector = {"worker": worker_id, "round": round_id}
                ids = await collection.insert_many([
                    {
                        **selector,
                        "sequence": sequence,
                        "payload": payload,
                        "updated": False,
                    }
                    for sequence in range(batch_size)
                ])
                assert len(ids) == batch_size
                assert len(set(ids)) == batch_size

                async with collection.find(selector).batch_size(7) as cursor:
                    documents = await cursor.to_list()
                assert {doc["_id"] for doc in documents} == set(ids)
                assert len(documents) == batch_size
                assert {doc["sequence"] for doc in documents} == set(
                    range(batch_size),
                )
                assert all(
                    doc["payload"] == payload and doc["updated"] is False
                    for doc in documents
                )

                assert await collection.update(Update(
                    selector, {"$set": {"updated": True}}, multi=True,
                )) == batch_size
                async with collection.find(selector).batch_size(9) as cursor:
                    updated = await cursor.to_list()
                assert {doc["_id"] for doc in updated} == set(ids)
                assert all(
                    doc["updated"] is True and doc["payload"] == payload
                    for doc in updated
                )
                assert await collection.delete(
                    Delete(selector, limit=0),
                ) == batch_size
                assert await collection.find_one(selector) is None

        await self.run_workers(start, [
            worker(worker_id) for worker_id in range(worker_count)
        ])
        assert await collection.count() == 0
        assert await self.database.ping()

    async def test_parallel_readers_and_writers_with_shared_documents(
        self,
    ) -> None:
        collection = await self.database.create_collection("shared")
        writer_count, reader_count, rounds, document_count = 16, 8, 8, 128
        payload = "shared-data-" * 180
        await collection.insert_many([
            {"sequence": sequence, "updates": 0, "payload": payload}
            for sequence in range(document_count)
        ])
        start = asyncio.Event()
        expected_updates = writer_count * rounds

        async def writer() -> None:
            await start.wait()
            for _ in range(rounds):
                assert await collection.update(Update(
                    {}, {"$inc": {"updates": 1}}, multi=True,
                )) == document_count

        async def reader() -> None:
            await start.wait()
            previous = dict.fromkeys(range(document_count), 0)
            for _ in range(rounds):
                async with collection.find().batch_size(17) as cursor:
                    documents = await cursor.to_list()
                assert len(documents) == document_count
                assert {doc["sequence"] for doc in documents} == set(previous)
                for document in documents:
                    sequence, updates = (
                        document["sequence"], document["updates"],
                    )
                    assert previous[sequence] <= updates <= expected_updates
                    assert document["payload"] == payload
                    previous[sequence] = updates

        await self.run_workers(start, [
            *(writer() for _ in range(writer_count)),
            *(reader() for _ in range(reader_count)),
        ])
        async with collection.find().batch_size(19) as cursor:
            documents = await cursor.to_list()
        assert len(documents) == document_count
        assert {doc["sequence"] for doc in documents} == set(
            range(document_count),
        )
        assert all(doc["updates"] == expected_updates for doc in documents)
        assert all(doc["payload"] == payload for doc in documents)
        assert await self.database.ping()


if __name__ == "__main__":
    unittest.main()
