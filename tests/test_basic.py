__import__("sys").path.append(
    str(__import__("pathlib").Path(__file__).parent.parent))
# be able to import stuff

import unittest  # noqa: E402
from uuid import uuid4, UUID  # noqa: E402

from bson import ObjectId, Binary  # noqa: E402

from kover.auth import AuthCredentials  # noqa: E402
from kover.client import Kover  # noqa: E402
from kover.schema import SchemaGenerator, Document  # noqa: E402


class User(Document):
    name: str
    age: int


class SubDocument(Document):
    a: int
    b: str


class Subclass(User):
    uuid: UUID
    subdocument: SubDocument


class AsyncTestExample(unittest.IsolatedAsyncioTestCase):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.schema_generator = SchemaGenerator()
        self.test_collection_name: str = "test"
        self.credentials = AuthCredentials(
            username="main_m1",
            password="incunaby!"
        )

    async def asyncSetUp(self) -> None:
        self.client = await Kover.make_client(credentials=self.credentials)
        assert self.client.signature is not None
        self.addAsyncCleanup(self.client.close)

    async def asyncTearDown(self) -> None:
        await self.client.db.drop_collection(self.test_collection_name)

    async def test_credentials_md5(self) -> None:
        hashed = self.credentials.md5_hash()
        assert hashed == b'f79a93932f4e10c3654be025a576398c'

    async def test_cursor(self) -> None:
        collection = await self.client.db.create_collection(
            self.test_collection_name
        )
        assert await collection.count() == 0

        users = [User("josh", age=50)] * 1000
        r = await collection.add_many(users)
        assert len(r) == 1000 and len(set(r)) == 1000
        cs = await collection.find().limit(1000).to_list()
        assert len(cs) == 1000

        cs = await collection.find().skip(10).to_list()
        assert len(cs) == 990
        await collection.delete_many()
        await collection.add_many([users[0]] * 75)
        cs = await collection.find(None).batch_size(50).to_list()
        assert len(cs) == 75

        cs = await collection.find({"test": "nonexistent"}).to_list()
        assert len(cs) == 0

        await collection.delete_many()

    async def test_collection_create(self):
        collection = await self.client.db.create_collection(
            self.test_collection_name
        )
        assert collection.name == self.test_collection_name and \
            collection.database.name == "db"

    async def test_basic_operations(self):
        collection = await self.client.db.create_collection(
            self.test_collection_name
        )

        user = User(name="dima", age=18)
        document = user.to_dict()
        count = await collection.count()
        assert count == 0

        obj_id = await collection.add_one(document)
        assert isinstance(obj_id, ObjectId)
        count = await collection.count()
        assert count == 1
        resp = await collection.find().to_list()
        assert isinstance(resp[0], dict)

        resp = await collection.find(cls=User).to_list()
        assert isinstance(resp[0], User)
        assert resp[0].name == "dima" and resp[0].age == 18
        assert not await collection.delete_one({"name": "drake"})
        assert await collection.delete_one({"name": "dima"})

    async def test_documents(self) -> None:
        assert issubclass(User, Document)
        user = User("john", 16)
        assert user._id is not None
        document = user.to_dict(exclude_id=False)
        assert "_id" in document
        document = user.to_dict()
        assert "_id" not in document
        serialized = User.from_document(document)
        assert serialized.name == "john" and serialized.age == 16
        assert isinstance(serialized, User) and serialized == user

        sbcls = Subclass("jora", 20, uuid4(), subdocument=SubDocument(1, "5"))
        deserialized = sbcls.to_dict()
        assert len(deserialized.keys()) == 4
        assert isinstance(deserialized["uuid"], Binary)
        assert issubclass(Subclass, User) and issubclass(Subclass, Document)
        serialized = Subclass.from_document(deserialized)
        assert isinstance(serialized.uuid, UUID) and \
            isinstance(serialized.subdocument, SubDocument)
        assert serialized.subdocument.a == 1 and \
            serialized.subdocument.b == "5"

    async def test_base_schema(self) -> None:
        schema = self.schema_generator.generate(User)
        self.assertEqual(schema, {
            '$jsonSchema': {
                'additionalProperties': False,
                'bsonType': ['object'],
                'properties': {
                    '_id': {
                        'bsonType': ['objectId']
                    },
                    'age': {
                        'bsonType': ['int']
                    },
                    'name': {
                        'bsonType': ['string']
                    }
                },
                'required': ['name', 'age', '_id']
            }
        })


if __name__ == "__main__":
    unittest.main()
