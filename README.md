# kover

![Build Status](https://img.shields.io/github/actions/workflow/status/megawattka/kover/actions.yml)
![License](https://img.shields.io/github/license/megawattka/kover)
![Python - Req](https://img.shields.io/badge/python-3.10+-blue)
![Pypi Status](https://img.shields.io/pypi/status/kover)
![Last Commit](https://img.shields.io/github/last-commit/megawattka/kover)
![MongoDB](https://img.shields.io/badge/MongoDB-6.0+-green)

**Kover** is a model-orientied strictly typed mongodb driver supporting local mongod, replica sets and remote atlases.<br>
this library was inspired by <a href=https://github.com/sakal/aiomongo>this project</a> i like it very much. Though its 9 years old.
Kover is linted by Ruff and supports pyright strict type checking mode.

```py
import asyncio

from kover import AuthCredentials, Kover


async def main():
    # or AuthCredentials.from_environ()
    # (requires MONGO_USER and MONGO_PASSWORD environment variables)
    # (remove if no auth present)
    credentials = AuthCredentials(username="...", password="...")
    client = await Kover.make_client(credentials=credentials)

    found = await client.db.test.find().limit(10).to_list()
    print(found)

if __name__ == "__main__":
    asyncio.run(main())
```

The main reason why i created this project is that Motor - official async wrapper for mongodb, uses ThreadPool executor and it's just a wrapper around pymongo. In general thats slower than clear asyncio and looks more dirty.
- 02.12.24 UPDATE: pymongo added async support but its kinda messed up. pymongo's code looks complicated, dirty and unclean.

# Status
it still missing features. <br>
e.g: **bulk write API** and **Encryption**
but its already very cool! <br>

# Dependencies
- All platforms.
- python 3.10+
- MongoDB 6.0+ (not sure about older versions)
- pydantic 2.10.6 or later
- dnspython 2.7.0 or later

# Features
Almost all features from pymongo. All auth types are supported. Integration with Pydantic supported.
this lib was built for new mongod versions. All features that were marked as DEPRECATED in docs
were NOT added. See docs for references. The kover.bson package was entirely copied from pymongo source code. I do not own these files.

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
import logging
from typing import Annotated

from pydantic import ValidationError

from kover import (
    AuthCredentials,
    Document,
    Kover,
    OperationFailure,
    SchemaGenerator,
)
from kover.metadata import SchemaMetadata

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class UserType(Enum):  # noqa: D101
    ADMIN = "ADMIN"
    USER = "USER"
    CREATOR = "CREATOR"


class Friend(Document):  # noqa: D101
    name: str
    age: Annotated[int, SchemaMetadata(minimum=18)]  # minimum age is 18.


# kover automatically generates aliases using camel case.
# so user_type will be "userType" in db
# if you still need to snake cased field_name
# use explicit alias="<snake_cased_name>"
class User(Document):  # noqa: D101
    name: Annotated[str, SchemaMetadata(description="must be a string")]
    age: Annotated[
        int,
        SchemaMetadata(
            description="age must be int and more that 18", minimum=18,
        ),
    ]
    user_type: Annotated[
        UserType,
        SchemaMetadata(description="can only be one of the enum values"),
    ]
    friend: Friend | None


async def main() -> None:  # noqa: D103
    credentials = AuthCredentials.from_environ()
    client = await Kover.make_client(credentials=credentials)

    generator = SchemaGenerator()
    schema = generator.generate(User)

    collection = await client.db.test.create_if_not_exists()
    await collection.set_validator(schema)

    valid_user = User(
        name="John Doe",
        age=20,
        user_type=UserType.USER,
        friend=Friend(name="dima", age=18),
    )
    # function accepts either valid_user or valid_user.to_dict()
    object_id = await collection.insert(valid_user)
    log.info(f"{object_id}, added!")

    try:
        invalid_user = User(
            name="Rick",
            age=15,
            user_type=UserType.ADMIN,
            friend=Friend(name="roma", age=25),
        )
    except ValidationError as e:  # it wont let you create such model
        raise SystemExit(e.errors()) from e

    # somehow if you try to insert invalid_user.to_dict()
    # kover.exceptions.ErrDocumentValidationFailure: Rick's age is less than 18
    try:
        await collection.insert(invalid_user)
    except OperationFailure as e:
        msg: str = e.message["errmsg"]
        log.info(f"got Error: {msg}")
        assert e.code == 121  # ErrDocumentValidationFailure  # noqa: E501, PT017


if __name__ == "__main__":
    asyncio.run(main())

```

### Transactions

```py
import asyncio
import logging
from typing import TYPE_CHECKING

from kover.bson import ObjectId

from kover import AuthCredentials, Kover

if TYPE_CHECKING:
    from kover import xJsonT

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def main() -> None:  # noqa: D103
    credentials = AuthCredentials.from_environ()
    client = await Kover.make_client(credentials=credentials)
    session = await client.start_session()

    # specify _id directly
    doc: xJsonT = {"_id": ObjectId(), "name": "John", "age": 30}
    collection = await client.db.test.create_if_not_exists()

    async with session.start_transaction() as transaction:
        await collection.insert(doc, transaction=transaction)
        # it should error with duplicate key now
        await collection.insert(doc, transaction=transaction)

    exc = transaction.exception  # if exist
    log.info(f"{exc}, {type(exc)}")
    log.info(f"trx state: {transaction.state}")

    found = await collection.find().to_list()
    log.info(found)  # no documents found due to transaction abort


if __name__ == "__main__":
    asyncio.run(main())

```

### GridFS

```py
import asyncio
import logging

from kover import AuthCredentials, Kover
from kover.gridfs import GridFS

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def main() -> None:  # noqa: D103
    credentials = AuthCredentials.from_environ()
    client = await Kover.make_client(credentials=credentials)

    database = client.get_database("files")
    fs = await GridFS(database).indexed()

    # can be bytes, any type of IO str or path
    file_id = await fs.put(b"Hello World!")

    file, binary = await fs.get_by_file_id(file_id)
    log.info(file, binary.read())

    files = await fs.list()
    log.info(f"total files: {len(files)}")

    deleted = await fs.delete(file_id)
    log.info(f"is file deleted? {deleted}")


if __name__ == "__main__":
    asyncio.run(main())

```

### Updating/Deleting docs

```py
import asyncio
import logging
from typing import TYPE_CHECKING

from kover import (
    AuthCredentials,
    Delete,
    Document,
    Kover,
    Update,
)

if TYPE_CHECKING:
    from kover.bson import ObjectId

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class User(Document):  # noqa: D101
    name: str
    age: int


async def main() -> None:  # noqa: D103
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
    log.info(f"documents deleted: {n}")  # 1


if __name__ == "__main__":
    asyncio.run(main())

```

# If you found a bug, open an issue, or even better create a pull request, thx ❤️