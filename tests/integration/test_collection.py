from uuid import UUID, uuid4

from elune import ObjectId

from kover import Delete, Document, Update
from tests.integration.base import MongoTestCase


class Sample(Document):
    name: str
    age: int
    uuid: UUID


class CollectionIntegrationTests(MongoTestCase):
    async def test_create_and_model_crud(self) -> None:
        collection = await self.database.create_collection("items")
        assert collection.name == "items"
        assert collection.database is self.database
        assert await collection.count() == 0
        sample = Sample(name="Alice", age=20, uuid=uuid4())
        document_id = await collection.insert_one(sample)
        assert isinstance(document_id, ObjectId)
        found = await collection.find_one({"_id": document_id}, cls=Sample)
        assert found is not None
        converted = found.model_dump()
        del converted["_id"]

        assert converted == sample.model_dump()
        assert isinstance(await collection.find_one(), dict)
        assert await collection.update(Update({"_id": document_id}, {
            "$set": {"age": 21},
        })) == 1
        updated = await collection.find_one({"_id": document_id}, cls=Sample)
        assert updated is not None
        assert updated.age == 21
        assert await collection.delete(Delete({"age": 99}, limit=1)) == 0
        assert await collection.delete(Delete({"age": 21}, limit=1)) == 1
        assert await collection.find_one() is None

    async def test_repeated_models_recv_distinct_ids_and_clear(self) -> None:
        collection = self.database.get_collection("items")
        sample = Sample(name="Alice", age=20, uuid=uuid4())
        ids = await collection.insert_many([sample] * 100)
        assert len(ids) == 100
        assert len(set(ids)) == 100

        assert await collection.count() == 100
        assert await collection.clear() == 100
        assert await collection.count() == 0
