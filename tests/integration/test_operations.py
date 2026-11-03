from __future__ import annotations

import os
from uuid import UUID, uuid4

from kover import Document
from tests.integration.base import MongoTestCase


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


class TestMethods(MongoTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.collection = self.database.get_collection("items")

    async def test_insert(self) -> None:
        doc = Sample.random()
        await self.collection.insert_one(doc)

        samples = [Sample.random() for _ in range(100)]
        r = await self.collection.insert_many(samples)
        assert len(r) == 100

        count = await self.collection.count()
        assert count == 101, count

        found = await self.collection.find_one({"name": doc.name}, cls=Sample)
        assert found is not None

        new = Sample(
            name=found.name,
            age=found.age,
            uuid=found.uuid,
        )
        assert new.to_dict() == doc.to_dict(), (new, doc)
