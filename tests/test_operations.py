from __future__ import annotations

import os
import unittest
from uuid import UUID, uuid4

from bson import ObjectId

from kover.auth import AuthCredentials
from kover.client import Kover
from kover.schema import Document


class Sample(Document):
    name: str
    age: int
    uuid: UUID

    @classmethod
    def random(cls) -> Sample:
        return cls(
            name=os.urandom(4).hex(),
            age=int.from_bytes(os.urandom(2), "little"),
            uuid=uuid4(),
        )


class TestMethods(unittest.IsolatedAsyncioTestCase):
    def __init__(self, *args: str, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.credentials = AuthCredentials(
            username="main_m1",
            password="incunaby!",
        )
        self.coll_name = "test"

    async def asyncSetUp(self) -> None:
        self.client = await Kover.make_client(credentials=self.credentials)
        assert self.client.signature is not None
        self.addAsyncCleanup(self.client.close)
        self.collection = self.client.db.get_collection(self.coll_name)

    async def asyncTearDown(self) -> None:
        await self.client.db.drop_collection(self.coll_name)

    async def test_insert(self) -> None:
        doc = Sample.random()
        obj_id = await self.collection.insert(doc)
        assert isinstance(obj_id, ObjectId)

        samples = [Sample.random() for _ in range(100)]
        ids = await self.collection.insert(samples)
        assert len(ids) == 100

        count = await self.collection.count()
        assert count == 101, count

        found = await self.collection.find_one({"name": doc.name}, cls=Sample)
        assert found == doc, (found, doc)


if __name__ == "__main__":
    unittest.main()
