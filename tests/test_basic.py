from __future__ import annotations

import unittest
from uuid import UUID, uuid4

from kover import (
    AuthCredentials,
    Delete,
    Document,
    Kover,
    SchemaGenerator,
)
from kover.bson import Binary


class User(Document):
    name: str
    age: int


class SubDocument(Document):
    a: int
    b: str
    uid: int


class Subclass(User):
    uuid: UUID
    subdocument: SubDocument


class BasicTests(unittest.IsolatedAsyncioTestCase):
    """Basic tests related to document operations."""

    def __init__(self, *args: str, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.schema_generator = SchemaGenerator()
        self.test_collection_name: str = "test"
        self.credentials = AuthCredentials(
            username="main_m1",
            password="incunaby!",
        )

    async def asyncSetUp(self) -> None:
        self.client = await Kover.make_client(credentials=self.credentials)
        assert self.client.signature is not None
        self.addAsyncCleanup(self.client.close)

    async def asyncTearDown(self) -> None:
        await self.client.db.drop_collection(self.test_collection_name)

    async def test_credentials_md5(self) -> None:
        hashed = self.credentials.md5_hash()
        assert hashed == b"f79a93932f4e10c3654be025a576398c"

    async def test_cursor(self) -> None:
        collection = await self.client.db.create_collection(
            self.test_collection_name,
        )
        assert await collection.count() == 0
        users = [User(name="josh", age=50)] * 1000
        r = await collection.insert_many(users)
        assert len(r) == 1000
        cs = await collection.find().limit(100).to_list()
        assert len(cs) == 100
        cs = await collection.find().skip(10).to_list()
        assert len(cs) == 990
        await collection.clear()
        await collection.insert_many([users[0]] * 75)
        cs = await collection.find().batch_size(50).to_list()
        assert len(cs) == 75

        cs = await collection.find({"test": "nonexistent"}).to_list()
        assert len(cs) == 0

        await collection.clear()

    async def test_collection_create(self) -> None:
        collection = await self.client.db.create_collection(
            self.test_collection_name,
        )
        assert collection.name == self.test_collection_name
        assert collection.database.name == "db"

    async def test_basic_operations(self) -> None:
        collection = await self.client.db.create_collection(
            self.test_collection_name,
        )

        user = User(name="dima", age=18)
        document = user.to_dict()
        count = await collection.count()
        assert count == 0

        await collection.insert_one(document)
        count = await collection.count()
        assert count == 1
        resp = await collection.find().to_list()
        assert isinstance(resp[0], dict)

        resp = await collection.find({}, cls=User).to_list()
        assert isinstance(resp[0], User)
        assert resp[0].name == "dima"
        assert resp[0].age == 18
        assert not await collection.delete(Delete({"name": "drake"}, limit=1))
        assert await collection.delete(Delete({"name": "dima"}, limit=1))

    async def test_documents(self) -> None:  # noqa: PLR6301
        assert issubclass(User, Document)
        user = User(name="john", age=16)
        assert user.get_id() is None
        document = user.to_dict()
        assert "_id" not in document
        serialized = User.from_document(document)
        assert isinstance(serialized, User)
        assert serialized.name == "john"
        assert serialized.age == 16
        assert serialized == user

        subdocument = SubDocument(a=1, b="5", uid=2893912931299219912919129)
        sbcls = Subclass(
            name="jora",
            age=20,
            uuid=uuid4(),
            subdocument=subdocument,
        )
        deserialized = sbcls.to_dict()
        assert len(deserialized.keys()) == 4
        assert isinstance(deserialized["uuid"], Binary)
        assert issubclass(Subclass, User)
        assert issubclass(Subclass, Document)
        serialized = Subclass.from_document(deserialized)
        assert isinstance(serialized.uuid, UUID)
        assert isinstance(serialized.subdocument, SubDocument)
        assert serialized.subdocument.a == 1
        assert serialized.subdocument.b == "5"

    async def test_base_schema(self) -> None:
        schema = self.schema_generator.generate(User)
        assert schema == {
            "$jsonSchema": {
                "additionalProperties": False,
                "bsonType": ["object"],
                "properties": {
                    "_id": {
                        "bsonType": ["objectId"],
                    },
                    "age": {
                        "bsonType": ["int", "long"],
                    },
                    "name": {
                        "bsonType": ["string"],
                    },
                },
                "required": ["name", "age", "_id"],
            },
        }


if __name__ == "__main__":
    unittest.main()
