# kover

![Build Status](https://img.shields.io/github/actions/workflow/status/oMegaPB/kover/actions.yml)
![License](https://img.shields.io/github/license/oMegaPB/kover)
![Python - Req](https://img.shields.io/badge/python-3.10.6+-blue)
![Pypi Status](https://img.shields.io/pypi/status/kover)
![Last Commit](https://img.shields.io/github/last-commit/oMegaPB/kover)
![MongoDB](https://img.shields.io/badge/MongoDB-6.0+-green)

**Kover** is a Model-orientied strict typed mongodb driver supporting local mongod and replica sets. Battle tests are still required*<br>
this library was inspired by <a href=https://github.com/sakal/aiomongo>this project</a> i like it very much. Though its 8 years old.

```py
import asyncio

from kover import Kover, AuthCredentials


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
- 02.12.24 UPDATE: pymongo added async support but its kinda slow same as sync version. pymongo's code looks dirty and have lots of unnecessary things. kover almost 2-3 times faster than pymongo.

# Status
it still missing features. <br>
e.g: **bulk write API** and **Compression**<br>
but its already very cool! <br>
ill be happy if someone can help me implement missing features.

# Dependencies
- All platforms.
- pymongo 4.10.1 (latest for now) or later.
- python 3.10.6
- im using MongoDB 7.0 but it should also work on MongoDB 6.0
- pydantic 2.10.6 or later

# Features
almost all features from pymongo. All auth types are supported. Integration with Pydantic supported.
this lib was built for new mongod versions. All features that were marked as DEPRECATED in docs
were NOT added. See docs for references

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
from kover import Document

class User(Document):
    uuid: UUID
    name: str
    age: int


async with db.test.find(cls=User).limit(1000) as cursor:
    async for item in cursor:
        print(item) # its now User

```

### Schema Validation
some people say that mongodb is dirty because you can insert any document in collection. Kover fixes that! Use `pydantic.Field` here if you need
Document is a Pydantic Model in 2.0
```py
import asyncio
from enum import Enum
from typing import Optional, Annotated

from pydantic import ValidationError

from kover import (
    SchemaGenerator,
    Document,
    Kover,
    AuthCredentials,
    OperationFailure
)
from kover.metadata import SchemaMetadata


class UserType(Enum):
    ADMIN = "ADMIN"
    USER = "USER"
    CREATOR = "CREATOR"


class Friend(Document):
    name: str
    age: Annotated[int, SchemaMetadata(minimum=18)]  # minimum age is 18.


# kover automatically generates aliases using camel case.
# so user_type will be "userType" in db
# if you still need to snake cased field_name
# use explicit alias="<snake_cased_name>"
class User(Document):
    name: Annotated[str, SchemaMetadata(description="must be a string")]
    age: Annotated[int, SchemaMetadata(
        description="age must be int and more that 18",
        minimum=18
    )]
    user_type: Annotated[UserType, SchemaMetadata(
        description="can only be one of the enum values"
    )]
    friend: Optional[Friend]


async def main():
    credentials = AuthCredentials.from_environ()
    kover = await Kover.make_client(credentials=credentials)

    generator = SchemaGenerator()
    schema = generator.generate(User)

    collection = await kover.db.test.create_if_not_exists()
    await collection.set_validator(schema)

    valid_user = User(
        name="John Doe",
        age=20,
        user_type=UserType.USER,
        friend=Friend(
            name="dima",
            age=18
        )
    )
    # function accepts either valid_user or valid_user.to_dict()
    object_id = await collection.insert(valid_user)
    print(object_id, "added!")

    try:
        invalid_user = User(
            name="Rick",
            age=15,
            user_type=UserType.ADMIN,
            friend=Friend(
                name="roma",
                age=25
            )
        )
    except ValidationError as e:  # it wont let you create such model
        raise SystemExit(e.errors())

    # kover.exceptions.ErrDocumentValidationFailure: Rick's age is less than 18
    try:
        await collection.insert(invalid_user)
    except OperationFailure as e:
        msg: str = e.message["errmsg"]
        print(f"got Error: {msg}")
        assert e.code == 121  # ErrDocumentValidationFailure

if __name__ == "__main__":
    asyncio.run(main())

```

### Transactions

```py
import asyncio

from bson import ObjectId

from kover.client import (
    Kover,
    xJsonT,
    AuthCredentials
)


async def main():
    credentials = AuthCredentials.from_environ()
    kover = await Kover.make_client(credentials=credentials)
    session = await kover.start_session()

    # specify _id directly
    doc: xJsonT = {"_id": ObjectId(), "name": "John", "age": 30}
    collection = await kover.db.test.create_if_not_exists()

    async with session.start_transaction() as transaction:
        await collection.insert(doc, transaction=transaction)
        # it should error with duplicate key now
        await collection.insert(doc, transaction=transaction)

    print(transaction.exception, type(transaction.exception))  # if exist
    print(transaction.state)

    found = await collection.find().to_list()
    print(found)  # no documents found due to transaction abort

if __name__ == "__main__":
    asyncio.run(main())

```

### GridFS

```py
import asyncio

from kover import Kover, AuthCredentials
from kover.gridfs import GridFS


async def main():
    credentials = AuthCredentials.from_environ()
    kover = await Kover.make_client(credentials=credentials)

    database = kover.get_database("files")
    fs = await GridFS(database).indexed()

    # can be bytes, any type of IO str or path
    file_id = await fs.put(b"Hello World!")

    file, binary = await fs.get_by_file_id(file_id)
    print(file, binary.read())

    files = await fs.list()
    print(f"total files: {len(files)}")

    deleted = await fs.delete(file_id)
    print("is file deleted?", deleted)

if __name__ == "__main__":
    asyncio.run(main())

```

### Updating/Deleting docs

```py
import asyncio

from bson import ObjectId

from kover import (
    Kover,
    Document,
    Update,
    Delete,
    AuthCredentials
)


class User(Document):
    name: str
    age: int


async def main():
    credentials = AuthCredentials.from_environ()
    kover = await Kover.make_client(credentials=credentials)

    collection = kover.db.get_collection("test")
    user = User(name="John", age=23)
    file_id: ObjectId = await collection.insert(user)  # or user.to_dict()

    # this concept requires using "$set" explicitly
    # if you dont specify it your entire doc will be
    # just replaced fully to specified here
    # advancements of this way is that you can do anything here not only "$set"
    # e.g {"$push": {"userIds": 12345}} and more
    # in conclusion: be careful with specifying "$set", dont forget it!
    update = Update({"_id": file_id}, {"$set": {"name": "Wick"}})
    await collection.update(update)

    # limit 1 corresponds to .delete_one and 0 to .delete_many
    delete = Delete({"_id": file_id}, limit=1)
    n = await collection.delete(delete)
    print(f"documents deleted: {n}")  # 1


if __name__ == "__main__":
    asyncio.run(main())

```

# If you found a bug, open issue pls. lib is still WIP