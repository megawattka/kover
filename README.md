# kover
![Build Status](https://img.shields.io/github/actions/workflow/status/megawattka/kover/actions.yml) ![License](https://img.shields.io/github/license/megawattka/kover) ![Python - Req](https://img.shields.io/badge/python-3.10+-blue) ![Pypi Status](https://img.shields.io/pypi/status/kover) ![Last Commit](https://img.shields.io/github/last-commit/megawattka/kover) ![MongoDB](https://img.shields.io/badge/MongoDB-6.0+-green)

Kover is a model-oriented, strictly-typed, and asynchronous Object-Document Mapper (ODM) for MongoDB. It was built from the ground up using `asyncio` to provide a clean and high-performance alternative to traditional database drivers that rely on thread pools.

This library is inspired by `aiomongo` but is modernized for recent versions of Python and MongoDB, with a strong emphasis on type safety and developer experience. Kover is linted with Ruff and supports `pyright`'s strict type-checking mode.

## Features

*   **Fully Asynchronous:** Uses `asyncio` for non-blocking database operations, avoiding the use of thread pool executors.
*   **Pydantic Integration:** Define your document schemas using Pydantic-style models for automatic validation and serialization.
*   **Strictly Typed:** Designed for modern Python, with full type hinting support for better static analysis and code completion.
*   **Modern MongoDB Support:** Built for MongoDB 6.0+ and omits deprecated features for a cleaner API.
*   **Comprehensive API:** Supports nearly all of PyMongo's features, including CRUD operations, bulk writes, transactions, and GridFS.
*   **Authentication:** Supports all standard MongoDB authentication mechanisms.

**Note:** The `kover.bson` package is adapted from the `pymongo` source code.

## Dependencies
- `Python 3.10+`
- `MongoDB 6.0+`
- `pydantic>=2.10.6`
- `dnspython>=2.7.0`

## Installation

```bash
pip install kover
```
Optional dependencies for compression can be installed with:
```bash
pip install kover[snappy,zstd]
```

## Quick Start

Connect to MongoDB, create a client, and perform a simple query.

```python
import asyncio
import logging

from kover import Kover

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

async def main():
    # Connect using a connection string
    client = await Kover.from_uri("mongodb://user:pass@host:port/?tls=false")
    
    # Or, create a client programmatically
    # from kover import AuthCredentials
    # credentials = AuthCredentials(username="<user>", password="<pass>")
    # client = await Kover.make_client(credentials=credentials)

    db = client.testdb
    collection = db.test_collection

    # Insert a document
    await collection.insert_one({"message": "Hello, Kover!"})

    # Find documents
    found = await collection.find().to_list()
    log.info(found)

    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
```

## Examples

### Defining Schemas with Pydantic

Kover leverages Pydantic for defining document structures. This provides data validation, serialization, and a clear, explicit schema.

```python
from uuid import UUID
from kover import Document

class User(Document):
    """A user document schema."""

    uuid: UUID
    name: str
    age: int
```

You can even generate and enforce a JSON schema on the collection in MongoDB.

```python
from kover import SchemaGenerator

# Generate a schema from the User model
generator = SchemaGenerator()
schema = generator.generate(User)

# Apply the schema to the collection
collection = await client.db.users.create_if_not_exists()
await collection.set_validator(schema)
```

### Inserting Documents

You can insert Pydantic model instances directly into a collection.

```python
from uuid import uuid4

user = User(name="Jane Doe", age=30, uuid=uuid4())
result = await client.db.users.insert_one(user)
log.info("Inserted user with ID: %s", result)
```

### Querying Documents

Kover's cursor provides a powerful and flexible way to retrieve data.

**Iterating over a Cursor:**
```python
# The cursor asynchronously yields `User` objects
async with client.db.users.find(cls=User).limit(100) as cursor:
    async for user in cursor:
        log.info("User: %s, Age: %d", user.name, user.age)
```

**Fetching all results into a list:**
```python
users_list = await client.db.users.find(cls=User).to_list()
```

### Updating and Deleting

Use `Update` and `Delete` models to construct operations. This approach makes it clear which documents are being targeted and what modifications are being made.

```python
from kover import Update, Delete

# Update a user's age
update = Update({"name": "Jane Doe"}, {"$set": {"age": 31}})
await client.db.users.update(update)

# Delete a user
delete = Delete({"name": "Jane Doe"}, limit=1)
n_deleted = await client.db.users.delete(delete)
log.info("Documents deleted: %d", n_deleted)
```

### Bulk Writes

Perform multiple operations in a single request for efficiency.

```python
from kover import BulkWriteBuilder, Update, Delete

builder = BulkWriteBuilder()
builder.add_insert([{"product": "A"}], ns="testdb.inventory")
builder.add_update(
    Update({"product": "A"}, {"$set": {"quantity": 10}}),
    ns="testdb.inventory",
)
builder.add_delete(Delete({"product": "A"}, limit=1), ns="testdb.inventory")

await client.bulk_write(builder.build())
```

### Transactions

Kover supports ACID transactions for operations that require atomicity.

```python
session = await client.start_session()
collection = client.db.test

async with session.start_transaction() as transaction:
    await collection.insert_one({"step": 1}, transaction=transaction)
    await collection.insert_one({"step": 2}, transaction=transaction)
    # The transaction will be automatically committed on successful exit.
    # If an exception occurs, it will be aborted.
```

### GridFS for Large Files

Store and retrieve large files (e.g., images, videos) seamlessly with GridFS.

```python
from kover.gridfs import GridFS

# Get a GridFS instance for a database
fs = await GridFS(client.get_database("files")).indexed()

# Put a file into GridFS
file_id = await fs.put(b"Hello, large world!", filename="greeting.txt")

# Retrieve the file
file_info, file_bytes_io = await fs.get_by_file_id(file_id)

log.info(file_info)
log.info(file_bytes_io.read())
```

## Found a Bug?

If you find a bug, please [open an issue](https://github.com/megawattka/kover/issues). Better yet, create a pull request with a fix. Contributions are welcome! ❤️