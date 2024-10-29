**Kover** is a object-orientied fully typed mongodb driver supporting local mongod and replica sets. Battle tests are still required*<br>
this library was inspired by <a href=https://github.com/sakal/aiomongo>this project</a> i like it very much. Though its 8 years old.

```py
import asyncio

from kover.client import Kover
from kover.auth import AuthCredentials


async def main():
    # or AuthCredentials.from_environ()
    # (requires MONGO_USER and MONGO_PASSWORD environment variables)
    # (remove if no auth present)
    credentials = AuthCredentials(username="username", password="password")
    kover = await Kover.make_client(credentials=credentials)

    found = await kover.db.test.find().limit(10).to_list()
    print(found)

if __name__ == "__main__":
    asyncio.run(main())
```

The main reason why i created this project is that Motor - official async wrapper for mongodb, uses ThreadPool executor and it's just a wrapper around pymongo. In general thats slower than clear asyncio and looks more dirty.

# Status
it still missing a lot of features. <br>
e.g: **gridFS**, **bulk write API**, **Compression**<br>
but its already very cool! <br>
ill be happy if someone can help me implement missing features.

# Dependencies
- Should be available on all platforms.
    (if not go create issue)
- pymongo 4.10.1 (latest for now) or later.
- python 3.10.6
- im using MongoDB 7.0 but it should also work on MongoDB 6.0
- attrs 24.2.0 or later for dataclass functionality

# Features
all basic features from pymongo and object-orientied functionality. All auth types are supported.

### Cursors
if you just need list:

```py
items = await db.test.find().limit(1000).batch_size(50).to_list()
```

### or
```py
async with db.test.find().limit(1000).batch_size(50) as cursor:
    async for item in cursor:
        print(item)
```
### if collection has specific schema:
```py
class User(Document):
    uuid: UUID
    name: str
    age: int


async with db.test.find({}, cls=User).limit(1000) as cursor:
    async for item in cursor:
        print(item) # its now User

```

### Schema Validation
some people say that mongodb is dirty because you can insert any document in collection. Kover fixes that!
```py
import asyncio
from enum import Enum
from typing import Optional

from kover.client import Kover
from kover.schema import SchemaGenerator, Document, field


class UserType(Enum):
    ADMIN = "ADMIN"
    USER = "USER"
    CREATOR = "CREATOR"


# can be used as annotation too
class Friend(Document):
    name: str
    age: int = field(min=18)  # minimum age is 18. less will error


# note field_name kwarg in user_type field.
# it'll be name of that key when using .to_dict()
class User(Document):
    name: str = field(description="must be a string")
    age: int = field(
        description="age must be int and more that 18", min=18
    )
    user_type: UserType = field(
        description="can only be one of the enum values",
        field_name="userType"
    )
    friend: Optional[Friend]


async def main():
    kover = await Kover.make_client()

    generator = SchemaGenerator()
    schema = generator.generate(User)

    collections = await kover.db.list_collections({"name": "test"})
    if not collections:  # create if not exists
        collection = await kover.db.create_collection("test")
    else:
        collection = collections[0]
    await collection.set_validator(schema)

    valid_user = User("John Doe", 20, UserType.USER, friend=Friend("dima", 18))

    # function accepts either valid_user or valid_user.to_dict()
    object_id = await collection.add_one(valid_user)
    print(object_id, "added!")

    invalid_user = User(
        "Rick",
        age=15,
        user_type=UserType.ADMIN,
        friend=Friend("roma", 25)
    )
    # kover.exceptions.ErrDocumentValidationFailure: Rick's age is less than 18
    await collection.add_one(invalid_user)

if __name__ == "__main__":
    asyncio.run(main())

```

### Transactions

```py
import asyncio

from bson import ObjectId

from kover.client import Kover
from kover.session import Transaction
from kover.typings import xJsonT


async def main():
    kover = await Kover.make_client()
    session = await kover.start_session()

    # specify _id directly
    doc: xJsonT = {"_id": ObjectId(), "name": "John", "age": 30}

    transaction: Transaction
    async with session.start_transaction() as transaction:
        await kover.db.test.add_one(doc, transaction=transaction)
        # it should error with duplicate key now
        await kover.db.test.add_one(doc, transaction=transaction)

    print(transaction.exception, type(transaction.exception))  # if exist
    print(transaction.state)

    found = await kover.db.test.find().to_list()
    print(found)  # no documents found due to transaction abort

if __name__ == "__main__":
    asyncio.run(main())

```

# Tests/Benchmarks
**will be available soon...**