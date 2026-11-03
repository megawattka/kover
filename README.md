# Kover

[![Build Status](https://img.shields.io/github/actions/workflow/status/megawattka/kover/actions.yml)](https://github.com/megawattka/kover/actions/workflows/actions.yml)
[![License](https://img.shields.io/github/license/megawattka/kover)](https://github.com/megawattka/kover/blob/master/LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![PyPI](https://img.shields.io/pypi/v/kover)](https://pypi.org/project/kover/)
[![Typing](https://img.shields.io/badge/typing-py.typed-blue)](https://peps.python.org/pep-0561/)

**Kover** is a pure-`asyncio`, strictly typed MongoDB driver and lightweight document toolkit for modern Python, deeply integrated with **Pydantic v2**.

Built directly over `asyncio` streams and the MongoDB Wire Protocol (`OP_MSG` and `OP_COMPRESSED`) without thread-pool wrappers, Kover provides ergonomic, strongly typed interfaces for clients, connection pools, databases, collections, lazy cursors, Pydantic documents, server-side `$jsonSchema` validation, bulk writes, sessions, ACID transactions, and GridFS.

> **Current release:** `3.0.0` &nbsp;|&nbsp; **Minimum Python version:** `3.12+`

> **Note:** Kover is not a drop-in clone of PyMongo or Motor. It exposes its own clean, modern, type-safe API designed specifically around Python 3.12+ generics and Pydantic v2 models. Always verify server-version requirements for specific MongoDB commands in the official MongoDB manual.

---

## Table of Contents

- [Key Features](#key-features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Documents & MongoDB Schema Generation](#documents--mongodb-schema-generation)
- [CRUD & Collection Operations](#crud--collection-operations)
- [Bulk Writes](#bulk-writes)
- [Sessions & ACID Transactions](#sessions--acid-transactions)
- [GridFS](#gridfs)
- [Authentication, TLS & Network Compression](#authentication-tls--network-compression)
- [Database, User & Server Administration](#database-user--server-administration)
- [Error Handling](#error-handling)
- [Examples](#examples)
- [Testing & Development](#testing--development)
- [Contributing & Feedback](#contributing--feedback)
- [License](#license)

---

## Key Features

- **Native `asyncio` Networking:** Communicates directly over `asyncio.StreamReader` / `asyncio.StreamWriter` using MongoDB's modern wire protocol (`OP_MSG` / `OP_COMPRESSED`) and a lazy `ConnectionPool`—zero thread-pool overhead.
- **First-Class Pydantic v2 Integration:** Define typed `Document` models with automatic BSON/Python serialization (`ObjectId`, `Binary`, `UUID`, `Decimal`, `Enum`, nested models, unions, and tuples).
- **MongoDB `$jsonSchema` Generation:** Compile Pydantic v2 models straight into MongoDB-compatible `$jsonSchema` validators via `Document.model_mongodb_schema()`, automatically resolving `$defs`/`$ref`, Draft 2020-12 constraints, and BSON type mappings.
- **Strictly Typed (`py.typed`):** Engineered for `pyright` in `strict` mode and linted with `ruff`. Overloaded query methods (`find`, `find_one`) return `Cursor[Model]` / `Model | None` when `cls=Model` is supplied, or `DictT` dictionaries otherwise.
- **Lazy Asynchronous Cursors:** Chainable query modifiers (`sort`, `skip`, `limit`, `batch_size`, `projection`, `hint`, `comment`, `collation`), async iteration, `first()`, `to_list()`, and deterministic `killCursors` cleanup via `async with`.
- **Rich MongoDB Feature Coverage:** Supports aggregation pipelines, index management, server-level `bulkWrite`, logical sessions, multi-document ACID transactions, user/role management, replica set administration, and **GridFS** for large files.
- **Security & Wire Compression:** Supports `SCRAM-SHA-256` and `SCRAM-SHA-1` authentication, TLS connections, and wire compression (`zlib` built-in; `snappy` and `zstd` via optional extras).

---

## Requirements

- **Python 3.12 or newer**
- A reachable **MongoDB** deployment (standalone, replica set, or sharded cluster).
  - Server version requirements depend on the commands used (e.g., multi-document transactions require a replica set or sharded cluster; server-level `bulkWrite` requires MongoDB 8.0+).

Core runtime dependencies (installed automatically):
- `pydantic >= 2.10.6`
- `pymongo >= 4.19` *(used strictly for its `bson` package and asynchronous MongoDB URI parser—all networking and protocol handling is native to Kover)*
- `typing-extensions >= 4.16.0`

---

## Installation

Install from PyPI using `pip` or [uv](https://docs.astral.sh/uv/):

```bash
pip install kover
# or
uv add kover
```

`zlib` compression works out of the box. For **Snappy** and **Zstandard (`zstd`)** wire compression, install the optional extras:

```bash
pip install "kover[snappy,zstd]"
# or
uv add "kover[snappy,zstd]"
```

---

## Quick Start

### Connecting via MongoDB URI

`Kover.from_uri()` parses MongoDB URI options, resolves the writable primary node, configures the connection pool, and closes idle connections when exiting `async with`:

```python
import asyncio
from kover import Kover


async def main() -> None:
    async with await Kover.from_uri("mongodb://127.0.0.1:27017/") as client:
        collection = client.get_database("demo").get_collection("messages")

        doc_id = await collection.insert_one({"message": "Hello, Kover!"})
        document = await collection.find_one({"_id": doc_id})
        print(document)


if __name__ == "__main__":
    asyncio.run(main())
```

### Connecting with Explicit Parameters

You can also construct a client programmatically via `Kover.make_client()`:

```python
from kover import AuthCredentials, Kover

credentials = AuthCredentials(
    username="my-user",
    password="my-password",
    auth_database="admin",
)

client = await Kover.make_client(
    host="127.0.0.1",
    port=27017,
    credentials=credentials,
    tls=False,
    compression=["zstd", "zlib"],
    w="majority",
    max_pool_size=50,
    application={"name": "my-service"},
)

try:
    print(await client.admin.ping())  # True
finally:
    await client.close()
```

Databases and collections can be retrieved via explicit methods or attribute notation:

```python
db = client.get_database("shop")      # or client.shop
orders = db.get_collection("orders")  # or client.shop.orders
files = client.shop.fs.files          # namespaced collection "fs.files"
```

---

## Documents & MongoDB Schema Generation

### Defining `Document` Models

`kover.Document` subclasses `pydantic.BaseModel` with `ConfigDict(extra="forbid", use_enum_values=True)` and stores MongoDB's `_id` in a private attribute so your domain model stays clean:

```python
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field
from kover import Document


class Role(StrEnum):
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class Profile(Document):
    bio: str
    rating: Annotated[float, Field(ge=0.0, le=5.0)] = 0.0


class User(Document):
    username: Annotated[str, Field(min_length=3, max_length=32)]
    age: Annotated[int, Field(ge=18, description="Must be at least 18")]
    role: Role = Role.MEMBER
    external_id: UUID = Field(default_factory=uuid4, alias="externalId")
    profile: Profile | None = None
```

Key `Document` methods:
- `doc.to_dict(exclude_id: bool = False) -> DictT` — dumps the model with `by_alias=True` (including `"_id"` when set).
- `Document.from_document(payload: DictT) -> Self` — validates a raw MongoDB document and attaches `_id`.
- `doc.get_object_id() -> ObjectId | None` / `doc.set_object_id(_id: ObjectId)` — get or set the document's `ObjectId`.
- `Document.model_mongodb_schema() -> DictT` — builds a MongoDB `$jsonSchema` validator dictionary.

> **Field Aliases:** `Document` dumps fields with `by_alias=True`. Use `Field(alias="camelName")` per field or configure `ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid", use_enum_values=True)` on a shared base class if you prefer automatic `camelCase` field names in MongoDB.

### Supported BSON & Python Types

Kover registers custom Pydantic core/JSON schemas for BSON types and translates Python/Pydantic annotations to MongoDB's `$jsonSchema` dialect:

| Python / Pydantic Type | BSON Representation | Generated MongoDB `bsonType` |
| --- | --- | --- |
| `str`, `bool`, `float` | UTF-8 String, Boolean, Double | `"string"`, `"bool"`, `"double"` |
| `int` | 32-bit / 64-bit Integer | `["int", "long"]` |
| `Decimal` / `Decimal128` | `Decimal128` | `"decimal"` |
| `bytes` / `bson.Binary` | `bson.Binary` | `"binData"` |
| `uuid.UUID` | Serialized via `Binary.from_uuid`, validated back to `UUID` | `"binData"` |
| `bson.ObjectId` | `bson.ObjectId` | `"objectId"` |
| `list[T]` / `tuple[T, ...]` | Array | `"array"` (`items` schema) |
| `tuple[T1, T2]` | Fixed-length Array | `"array"` (`items` list; `prefixItems` converted) |
| `dict[str, T]` | Embedded Document | `"object"` (`additionalProperties` schema) |
| `Document` subclass | Embedded Document | `"object"` (`properties` + `required`) |
| `Enum` / `Literal[...]` | Underlying scalar value | `enum` + inferred `bsonType` |
| `T \| None` / Unions | Nullable / Union | `anyOf` / `oneOf` with `"null"` |

### Generating & Applying `$jsonSchema` Validators

MongoDB's `$jsonSchema` validator rejects standard JSON Schema Draft 2020-12 keywords like `$defs`, `$ref`, numeric `exclusiveMinimum`, `const`, `format`, and `prefixItems`. Kover's `MongoDBSchemaGenerator` (used by `Document.model_mongodb_schema()`) automatically resolves and converts them into valid MongoDB validation rules:

```python
from kover import ValidationLevel
from kover.exceptions import OperationFailure

validator = User.model_mongodb_schema()
# {"$jsonSchema": {"bsonType": "object", "properties": {...}, ...}}

# Apply to an existing or newly created collection:
users = await client.demo.users.create_if_not_exists()
await users.set_validator(validator, level=ValidationLevel.STRICT)

# Or pass directly during collection creation:
await client.demo.create_collection(
    "strict_users",
    params={"validator": validator, "validationLevel": "strict"},
)

# Insert a typed Document directly
alice_id = await users.insert_one(User(username="alice", age=27))

# Invalid raw documents are rejected by MongoDB (code 121: DocumentValidationFailure)
try:
    await users.insert_one({"username": "bob", "age": 15})
except OperationFailure as exc:
    print(exc.code, type(exc).__name__)  # 121 DocumentValidationFailure
```

---

## CRUD & Collection Operations

### Inserting, Querying & Lazy Async Cursors

`insert_one` and `insert_many` accept either raw `dict` payloads or `Document` instances. Passing `cls=Model` to `find_one` or `find` enables automatic Pydantic deserialization and static type inference:

```python
from kover import Collation, CollationStrength

await users.insert_many([
    User(username="charlie", age=31),
    User(username="dana", age=24),
])

# Typed single lookup -> User | None (omit cls= for dict[str, Any] | None)
user: User | None = await users.find_one({"username": "charlie"}, cls=User)

# Lazy cursor: configure options via chaining before iteration starts
cursor = (
    users.find({"age": {"$gte": 21}}, cls=User)
    .sort({"age": -1})
    .skip(0)
    .limit(50)
    .batch_size(25)
    .projection({"username": 1, "age": 1, "role": 1, "externalId": 1})
    .collation(Collation(locale="en", strength=CollationStrength.SECONDARY))
    .comment("active adult users")
)

# Stream with deterministic killCursors cleanup on early exit:
async with cursor as stream:
    async for item in stream:
        print(item.get_object_id(), item.username, item.age)

# Or materialize / inspect results directly:
all_users: list[User] = await users.find({"age": {"$gte": 21}}, cls=User).to_list()
first_user: User = await users.find({"age": {"$gte": 21}}, cls=User).first()
total: int = await users.count({"role": "MEMBER"})
roles: list[str] = await users.distinct("role")
```

> **Note:** A single `Cursor` does not support concurrent reads across tasks. Wrap `async for` in `async with cursor:` if you might break out early so open server cursors are killed immediately.

### Updating & Deleting Documents

Updates and deletes use explicit `Update` and `Delete` operation models:

```python
from kover import Delete, Update

# Update one document (multi=False by default)
await users.update(
    Update({"username": "charlie"}, {"$set": {"age": 32}}, upsert=False)
)

# Batch multiple update specs in one command
await users.update_many([
    Update({"role": "MEMBER"}, {"$set": {"profile": {"bio": "New", "rating": 5.0}}}, multi=True),
])

# Delete one (limit=1) or all matching documents (limit=0)
deleted_one = await users.delete(Delete({"username": "dana"}, limit=1))
deleted_many = await users.delete_many([Delete({"age": {"$lt": 20}}, limit=0)])

# Remove all documents from the collection
cleared = await users.clear()
```

> **Important:** Always use update operators (`$set`, `$inc`, `$push`, etc.) in `Update(q, u)` when modifying specific fields—passing a plain dictionary without `$`-operators replaces the entire document!

### Aggregation, Indexes & Collection Utilities

```python
from kover import Index, IndexDirection, IndexType

# Aggregation pipeline (returns Cursor[DictT])
pipeline = [
    {"$match": {"age": {"$gte": 18}}},
    {"$group": {"_id": "$role", "count": {"$sum": 1}}},
]
stats = await users.aggregate(pipeline, allow_disk_use=True).to_list()

# Index management
await users.create_indexes(
    Index("username_unique_idx", {"username": IndexDirection.ASCENDING}, unique=True),
    Index("bio_text_idx", {"profile.bio": IndexType.TEXT}),
)
indexes: list[Index] = await users.list_indexes()
await users.re_index()
await users.drop_indexes("bio_text_idx")  # or drop_indexes(drop_all=True)

# Collection lifecycle & options
info_coll = await users.with_options()
await users.convert_to_capped(size=10 * 1024 * 1024)
await users.drop()
```

---

## Bulk Writes

`BulkWriteBuilder` constructs a server-level `bulkWrite` command capable of targeting multiple `database.collection` namespaces in a single round-trip:

```python
from kover import BulkWriteBuilder, Delete, Update

builder = BulkWriteBuilder(
    ordered=True,
    bypass_document_validation=False,
    errors_only=False,
    write_concern="majority",
)
builder.add_insert([{"sku": "A-1", "quantity": 5}], ns="demo.inventory")
builder.add_update(
    Update({"sku": "A-1"}, {"$set": {"quantity": 10}}),
    ns="demo.inventory",
)
builder.add_delete(Delete({"sku": "obsolete"}, limit=1), ns="demo.inventory")

results = await client.bulk_write(builder.build()).to_list()
```

---

## Sessions & ACID Transactions

Start a logical session via `await client.start_session()` and execute atomic multi-document operations inside `async with session.start_transaction() as transaction:`:

```python
from kover.exceptions import OperationFailure

session = await client.start_session()
orders = await client.demo.orders.create_if_not_exists()

try:
        session.start_transaction()
        await orders.insert_one({"status": "created"}, session=session)
        await orders.insert_one({"status": "queued"}, session=session)
        await session.commit_transaction()
        # Automatically commits on clean exit; aborts if any exception is raised.
except OperationFailure as exc:
    if exc.transaction is not None:
        print("Transaction state:", exc.transaction.state)  # TxnState.ABORTED
finally:
    await client.end_sessions([session])
```

> Multi-document transactions require a MongoDB replica set or sharded cluster deployment. You can also refresh active sessions with `await client.refresh_sessions([session])`.

---

## GridFS

Store, stream, list, and delete files exceeding BSON's 16 MB document size limit using `kover.gridfs.GridFS`. Payloads can be `bytes`, `str`, `pathlib.Path`, or file-like `BinaryIO` objects:

```python
from pathlib import Path
from kover.gridfs import GridFS, GridFSFileNotFound

# Initialize GridFS (uses "fs.files" and "fs.chunks" by default) and ensure indexes
fs = await GridFS(client.get_database("files"), collection="fs").indexed()

# Upload bytes, strings, Paths, or BinaryIO streams (SHA-1 stored in metadata by default)
file_id = await fs.put(
    b"Hello from GridFS!",
    filename="hello.txt",
    metadata={"contentType": "text/plain"},
)

# Download by ObjectId or filename (verifies SHA-1 automatically when present)
file_doc, content_stream = await fs.get_by_file_id(file_id)
print(file_doc.filename, file_doc.length, content_stream.read())

same_doc, _ = await fs.get_by_filename("hello.txt")

# Inspect & manage stored files
print(await fs.exists(file_id))  # True
all_files = await fs.list()      # list[File]
await fs.delete(file_id)         # Deletes file document and all associated chunks
```

---

## Authentication, TLS & Network Compression

- **URI Configuration:** Pass standard MongoDB URI options to `Kover.from_uri()`, e.g.:
  ```python
  client = await Kover.from_uri(
      "mongodb://user:pass@127.0.0.1:27017/demo"
      "?authSource=admin&tls=true&compressors=zstd,zlib&maxPoolSize=100&w=majority"
  )
  ```
  URL-encode special characters in usernames/passwords according to the MongoDB URI specification, and avoid hardcoding secrets in source code.
- **Environment Credentials:** `AuthCredentials.from_environ()` reads `MONGO_USER` and `MONGO_PASSWORD` from the environment:
  ```bash
  export MONGO_USER="my-user"
  export MONGO_PASSWORD="my-password"
  ```
  It returns `None` when neither variable is set, or raises `CredentialsException` if only one of the two is provided.
- **Supported Auth Mechanisms:** Negotiates `SCRAM-SHA-256` or `SCRAM-SHA-1` automatically during the `hello` handshake.
- **Write & Read Concerns:** Configure global client write concern via `client.set_write_concern(w="majority", j=True, wtimeout=5000)` or pass `WriteConcern` / `ReadConcern` per operation.

---

## Database, User & Server Administration

### Database & User Management (`Database`)

```python
db = client.get_database("demo")

# Health check & raw database commands
await db.ping()  # True
server_status = await db.command({"dbStats": 1})

# Collections management
collections = await db.list_collections()              # list[Collection]
names = await db.list_collections(name_only=True)      # list[str]
await db.drop_collection("old_logs")

# User & role administration
await db.create_user(
    "analytics",
    "s3cr3t-pass",
    roles=[{"role": "read", "db": "demo"}],
)
await db.grant_roles_to_user("analytics", [{"role": "readWrite", "db": "demo"}])
users_list = await db.users_info("analytics", show_privileges=True)
await db.drop_user("analytics")
```

### Server & Replica Set Administration (`Kover`)

```python
from kover import ReplicaSetConfig

info = await client.build_info()                  # BuildInfo (version, storage_engines, ...)
dbs = await client.list_database_names()          # list[str]
await client.rename_collection("demo.old", new_name="demo.new", drop_target=False)
await client.drop_database("staging_tmp")

# Runtime parameters, logs, and fsync locks
max_bson = await client.get_parameter("maxBSONDepth")
startup_logs = await client.get_log("startupWarnings")
read_concern, write_concern = await client.get_default_rw_concern()
await client.fsync(lock=True)
await client.fsync_unlock()

# Replica set operations
await client.replica_set_initiate(ReplicaSetConfig.default())
rs_status = await client.get_replica_set_status()

# Arbitrary low-level command against any database
raw_reply = await client.request({"hello": 1.0}, db_name="admin")
```

---

## Error Handling

All MongoDB server and write errors inherit from `kover.exceptions.OperationFailure`:

- **`OperationFailure`** — Carries `.code` (`int`), `.message` (`str | DictT`), `.err_info` (detailed validation failure info when returned by MongoDB), and `.transaction` (`Transaction | None` if raised inside a transaction).
  - Kover dynamically maps hundreds of MongoDB server error codes to dedicated `OperationFailure` subclasses (e.g., `11000` -> `DuplicateKey`, `121` -> `DocumentValidationFailure`, `13` -> `Unauthorized`, `18` -> `AuthenticationFailed`). Catch `OperationFailure` and inspect `exc.code` or `type(exc).__name__`.
- **`CredentialsException`** — Raised by `AuthCredentials.from_environ()` when only one of `MONGO_USER` or `MONGO_PASSWORD` is set.
- **`SchemaGenerationException`** — Schema validation and document deserialization exception.
- **`GridFSFileNotFound`** / **`IncorrectGridFSData`** — Raised by `kover.gridfs.GridFS` when a requested file does not exist or an unsupported payload type is passed to `put()`.

---

## Examples

Runnable scripts demonstrating core features are located in [`examples/`](https://github.com/megawattka/kover/tree/master/examples):

- [`examples/schema.py`](examples/schema.py) — Pydantic `Document` models, `model_mongodb_schema()`, and server-side collection validation.
- [`examples/update_delete.py`](examples/update_delete.py) — Inserting `Document` models and using `Update` (`$set`) and `Delete`.
- [`examples/bulk_write.py`](examples/bulk_write.py) — Multi-operation `BulkWriteBuilder` pipelines.
- [`examples/transactions.py`](examples/transactions.py) — Sessions, `async with session.start_transaction()`, and automatic abort on duplicate key errors.
- [`examples/gridfs.py`](examples/gridfs.py) — Uploading, reading, listing, and deleting files in `GridFS`.

Most examples connect to `127.0.0.1:27017` and read optional credentials via `AuthCredentials.from_environ()` (`MONGO_USER` and `MONGO_PASSWORD`).

---

## Testing & Development

Install development dependencies (using `uv` or `pip`):

```bash
uv sync --dev
```

### Unit Tests (No MongoDB Server Required)

```bash
# Run unittest suite
python -m unittest discover -s tests/unit -v

# Run pytest suite (including schema generation tests)
pytest tests/unit -v
```

### Integration Tests (Requires Running MongoDB)

Integration tests are skipped by default unless explicitly enabled via environment variables:

```bash
export KOVER_RUN_INTEGRATION=1
export MONGO_HOST=127.0.0.1
export MONGO_PORT=27017
# Optional authentication for unittest integration suite:
export MONGO_USER="my-user"
export MONGO_PASSWORD="my-password"

# URI used by pytest schema integration suite:
export MONGODB_URI="mongodb://127.0.0.1:27017/"

python -m unittest discover -s tests/integration -v
pytest tests/integration -v
```

### Type Checking & Linting

Kover enforces **strict** static typing with Pyright and comprehensive linting rules with Ruff:

```bash
pyright ./
ruff check ./
```

---

## Contributing & Feedback

Contributions, bug reports, and feature requests are welcome!

- **Report a bug or suggest a feature:** [GitHub Issues](https://github.com/megawattka/kover/issues)
- **Source code & pull requests:** [GitHub Repository](https://github.com/megawattka/kover)
- **Community guidelines:** Please review our [Code of Conduct](CODE_OF_CONDUCT.md).

---

## License

Distributed under the [MIT License](LICENSE). Copyright (c) 2024–present `megawattka`.
