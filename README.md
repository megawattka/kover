kover is a simple fully typehinted mongodb driver supporting local mongod and replica sets. works well for highly loaded projects.

```py
import asyncio

from kover.client import Kover
from kover.auth import AuthCredentials

async def main():
    credentials = AuthCredentials(username="username", password="password") # if your db requires auth
    kover = await Kover.make_client(credentials=credentials)
    db = kover.db # or kover.get_database("db")
    collections = await db.collection_names()
    print(collections)

if __name__ == "__main__":
    asyncio.run(main())
```

The main reason why i created this project is that Motor, official async wrapper for mongodb, uses ThreadPool executor. In general thats slower than clear asyncio and looks more dirty.

# Status
it still missing a lot of features. <br>
e.g: **gridFS**, **bulk write API**, read-write preferences, concerns<br>
but its already very useful <br>
ill be happy if someone can help me implement missing features.

# Dependencies
- Preferably linux. it requires some changes for windows and macOS.
- pymongo 4.10.1 (latest for now) or later.
- python 3.10.6
- im using MongoDB 7.0 but it should also work on MongoDB 6.0

# Features
the driver designed to be almost same as pymongo's while its fully async. btw supported auth types are SCRAM-SHA1 and SCRAM-SHA256

### Cursors
if you just need list:

```py
items = await db.test.find({"amount": 10}).limit(1000).batch_size(100).to_list()
```

### or
```py
async with db.test.find({"amount": 10}).limit(1000).batch_size(100) as cursor:
    async for item in cursor:
        print(item)
```

### Schema Validation
some people say that mongodb is dirty because you can insert any document in collection. Kover fixes that!
```py
import asyncio
from enum import Enum

from attrs import define, field

from kover.client import Kover
from kover.schema import SchemaGenerator, Document

class UserType(Enum): 
    ADMIN = "ADMIN"
    USER = "USER"
    CREATOR = "CREATOR"

@define # entities must be annotated with @define
class User(Document): # and subclassed from kover.schema.Document
    name: str = field(metadata={"description": "must be a string and is required"})
    age: int = field(metadata={"min": 18, "description": "age must be int and more that 18"})
    user_type: UserType = field(metadata={"description": "can only be one of the enum values and is required", "fieldName": "userType"})

@define # subdocument
class Friend: # must not subclassed from kover.schema.Document
    name: str
    description: str
# now it can be used as annotation

### note fieldName in user_type metadata. it will be key of that attribute when using .to_dict()

async def main():
    kover = await Kover.make_client()
    generator = SchemaGenerator()
    schema = generator.generate(User)

    await kover.db.create_collection("test")
    await kover.db.test.coll_mod({"validator": schema, "validationLevel": "moderate"})
    # can be one-lined to await kover.db.create_collection("test", {"validator": schema, "validationLevel": "moderate"})

    valid_user = User("John Doe", 20, UserType.USER)
    object_id = await kover.db.test.add_one(valid_user.to_dict())
    print(object_id, "added!")

    invalid_user = User("Rick", 15, UserType.ADMIN)
    await kover.db.test.add_one(invalid_user.to_dict()) # Error: age is less than 18

if __name__ == "__main__":
    asyncio.run(main())
```

### Transactions

```py
import asyncio

from bson import ObjectId

from kover.client import Kover
from kover.session import Transaction

async def main():
    kover = await Kover.make_client()
    session = await kover.start_session()
    doc = {"_id": ObjectId(), "name": "John", "age": 30} # specify _id directly
    
    transaction: Transaction
    async with session.start_transaction() as transaction:
        await kover.db.test.add_one(doc, transaction=transaction)
        await kover.db.test.add_one(doc, transaction=transaction) # it should error with duplicate key
    
    print(transaction.exception, type(transaction.exception)) # if exist
    print(transaction.state)

    found = await kover.db.test.find().to_list()
    print(found) # no documents found due to transaction abort

if __name__ == "__main__":
    asyncio.run(main())
```

# Tests/Benchmarks
**will be available soon...**