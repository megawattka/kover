__import__("sys").path.append(str(__import__("pathlib").Path(__file__).parent.parent)) # be able to import stuff

import pytest

from bson import ObjectId
from attrs import define

from kover.auth import AuthCredentials
from kover.client import Kover
from kover.schema import SchemaGenerator, Document

CREDENTIALS: AuthCredentials = AuthCredentials(username="main_m1", password="incunaby!")

@pytest.mark.asyncio
async def test_credentials():
    hashed = CREDENTIALS.md5_hash()
    assert hashed == b'f79a93932f4e10c3654be025a576398c'

@pytest.mark.asyncio
async def test_init():
    credentials = AuthCredentials(username="main_m1", password="incunaby!")
    kover = await Kover.make_client(credentials=credentials)
    assert kover.signature is not None

@define
class User(Document):
    name: str
    age: int

@pytest.mark.asyncio
async def test_entity():
    assert issubclass(User, Document)
    user = User("john", 16)
    assert user._id is not None

    document = user.to_dict(exclude_id=False)
    assert "_id" in document.keys()

    document = user.to_dict()
    assert "_id" not in document.keys()

@pytest.mark.asyncio
async def test_schema():
    generator = SchemaGenerator()
    schema = generator.generate(User)
    assert schema == {
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
            'required': ['_id', 'name', 'age']
        }
    }

@pytest.mark.asyncio
async def test_find_count_documents_and_delete():
    kover = await Kover.make_client(credentials=CREDENTIALS)
    
    collection = kover.test.tests
    await collection.delete_many({})
    user = User("dima", 18)
    document = user.to_dict()

    count = await collection.count()
    assert count == 0

    obj_id = await collection.add_one(document)
    assert isinstance(obj_id, ObjectId)
    count = await collection.count()
    assert count == 1

    resp = await collection.find({"name": "dima"}).to_list()
    found = User.from_document(resp[0])

    assert found.name == "dima" and found.age == 18
    deleted = await collection.delete_one({"name": "drake"})
    assert not deleted
    deleted = await collection.delete_one({"name": "dima"})
    assert deleted