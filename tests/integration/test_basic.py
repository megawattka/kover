from __future__ import annotations

from uuid import UUID, uuid4

from kover import (
    AuthCredentials,
    Delete,
    Document,
)
from tests.integration.base import MongoTestCase


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


class BasicTests(MongoTestCase):
    """Basic tests related to document operations."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.test_collection_name = "items"

    @staticmethod
    async def test_credentials_md5() -> None:
        credentials = AuthCredentials(
            username="user",
            password="password",  # ruff: ignore[hardcoded-password-func-arg]
        )
        assert credentials.md5_hash() == b"3bcfc22a1cd6be41bc7814c13d3ce94c"

    async def test_cursor(self) -> None:
        collection = await self.database.create_collection(
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
        collection = await self.database.create_collection(
            self.test_collection_name,
        )
        assert collection.name == self.test_collection_name
        assert collection.database is self.database

    async def test_basic_operations(self) -> None:
        collection = await self.database.create_collection(
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

    async def test_documents(self) -> None:  # ruff: ignore[no-self-use]
        assert issubclass(User, Document)
        user = User(name="john", age=16)
        assert user.get_object_id() is None
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
        assert isinstance(deserialized["uuid"], UUID)
        assert issubclass(Subclass, User)
        assert issubclass(Subclass, Document)
        serialized = Subclass.from_document(deserialized)
        assert isinstance(serialized.uuid, UUID)
        assert isinstance(serialized.subdocument, SubDocument)
        assert serialized.subdocument.a == 1
        assert serialized.subdocument.b == "5"

    @staticmethod
    async def test_base_schema() -> None:
        schema = User.model_mongodb_schema()
        assert schema == {
            "$jsonSchema": {
                "additionalProperties": False,
                "properties": {
                    "name": {
                        "bsonType": "string",
                    },
                    "age": {
                        "bsonType": [
                            "int",
                            "long",
                        ],
                    },
                    "_id": {
                        "bsonType": "objectId",
                    },
                },
                "required": [
                    "name",
                    "age",
                    "_id",
                ],
                "title": "User",
                "bsonType": "object",
            },
        }
