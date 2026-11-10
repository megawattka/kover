# Kover

[![Build Status](https://img.shields.io/github/actions/workflow/status/megawattka/kover/actions.yml)](https://github.com/megawattka/kover/actions/workflows/actions.yml)
[![License](https://img.shields.io/github/license/megawattka/kover)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![PyPI](https://img.shields.io/pypi/v/kover)](https://pypi.org/project/kover/)
[![Typing](https://img.shields.io/badge/typing-py.typed-blue)](https://peps.python.org/pep-0561/)

**Kover** is an asynchronous MongoDB driver and Pydantic v2 document toolkit
for Python 3.12+. Networking uses `asyncio` streams and MongoDB's `OP_MSG` /
`OP_COMPRESSED` wire protocol directly, without thread-pool wrappers.

## Contents

- [Capabilities and requirements](#capabilities-and-requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Connections and routing](#connections-and-routing)
- [Typed documents and BSON](#typed-documents-and-bson)
- [MongoDB schema validation](#mongodb-schema-validation)
- [CRUD and cursors](#crud-and-cursors)
- [Bulk writes](#bulk-writes)
- [Sessions and transactions](#sessions-and-transactions)
- [GridFS](#gridfs)
- [Errors](#errors)
- [Development](#development)
- [Documentation and examples](#documentation-and-examples)

## Capabilities and requirements

- Native asynchronous clients, per-server connection pools, and lazy cursors.
- All five read preference modes, ordered tag sets, max staleness, and latency windows.
- Pydantic `Document` models and strict MongoDB `$jsonSchema` generation.
- CRUD, aggregation, indexes, database/user administration, and GridFS.
- Logical sessions and explicit multi-document transactions.
- SCRAM-SHA-256 / SCRAM-SHA-1 authentication, TLS, and negotiated compression.

Requires Python **3.12+** and a reachable MongoDB deployment. Transactions need
a replica set or sharded cluster; server-level `bulkWrite` needs MongoDB
**8.0+**. Check MongoDB's version requirements for other commands you use.

Runtime dependencies:

| Dependency | Minimum version |
| --- | --- |
| `bson` | `0.4.0` |
| `dnspython` | `2.7.0` |
| `pydantic` | `2.14.3` |
| `typing-extensions` | `4.16.0` |

Kover uses the BSON implementation from **https://python.wattka.dev/**,
including its native Pydantic integration. Do not install PyMongo alongside
it: both provide the `bson` import namespace.

## Installation

The repository configures BSON's source explicitly in `pyproject.toml`:

```toml
[tool.uv.sources]
bson = { index = "bson" }

[[tool.uv.index]]
name = "bson"
url = "https://python.wattka.dev/"
explicit = true
```

For a separate application using uv, include the same BSON source/index mapping
in its `pyproject.toml`, then add Kover:

```bash
uv add kover
# Optional Snappy and Zstandard compression:
uv add "kover[snappy,zstd]"
```

`zlib` compression needs no extra dependency. The explicit index is used only
for packages mapped to it, rather than as a general package source.

## Quick start

`from_uri()` and `make_client()` are **module-level factory functions** returning
a `Kover` client. They are not methods on the `Kover` class. Factories perform
initial server discovery; application connections are opened lazily in pools.

```python
import asyncio

from kover import from_uri


async def main() -> None:
    async with await from_uri("mongodb://127.0.0.1:27017/") as client:
        messages = client.get_database("demo").get_collection("messages")
        document_id = await messages.insert_one({"message": "Hello, Kover!"})
        print(await messages.find_one({"_id": document_id}))


if __name__ == "__main__":
    asyncio.run(main())
```

The remaining asynchronous snippets belong inside an async function. Unless a
snippet creates its own client, it assumes an open `client` and reuses models
and collection handles introduced earlier. Close clients with `async with`
or `await client.close()` when finished.

## Connections and routing

### Explicit configuration

```python
from kover import AuthCredentials, make_client

client = await make_client(
    host="127.0.0.1",
    port=27017,
    credentials=AuthCredentials.from_environ(),
    tls=False,
    compression=["zlib"],
    max_pool_size=50,
    application={"name": "my-service"},
)
try:
    print(await client.admin.ping())
finally:
    await client.close()
```

`AuthCredentials.from_environ()` reads `MONGO_USER`, `MONGO_PASSWORD`, and
optional `MONGO_AUTH_DB` (default `admin`). It returns `None` if neither
credential is set and raises `CredentialsException` if only one is provided.
URI credentials use `authSource`, then the URI database, then `admin`.
Percent-encode reserved characters in URI usernames and passwords.

URI configuration supports TLS and compressor negotiation, for example
`mongodb://user:pass@host/demo?authSource=admin&tls=true&compressors=zlib`.
Do not hardcode production secrets. Authentication selects SCRAM-SHA-256 or
SCRAM-SHA-1 from the mechanisms advertised by `hello`.

### Discovery and timeouts

URI seeds are probed concurrently; discovery follows replica set members
advertised by `hello`. Use hostnames reachable as advertised in the replica
set configuration, not just reachable seed aliases.

| URI option | `make_client()` argument | Default |
| --- | --- | --- |
| `replicaSet` | `replica_set` | No expected set name |
| `directConnection` | `direct_connection` | `False` |
| `serverSelectionTimeoutMS` | `server_selection_timeout` | 30 seconds |
| `connectTimeoutMS` | `connect_timeout` | 10 seconds |
| `localThresholdMS` | `local_threshold` | 0.015 seconds |
| `maxPoolSize` | `max_pool_size` | 100 connections per server |

URI timeout/latency values in this table use milliseconds; programmatic
arguments use seconds. `connect_timeout` limits each discovery probe and each
new pooled connection's setup, including handshake/authentication.
`connect_timeout=None` (`connectTimeoutMS=0`) disables those individual limits,
not the server-selection or explicit operation deadline.

`server_selection_timeout` limits selection, not command execution. Neither
setting is a socket timeout for commands on established connections.
`client.command()` and `Database.command()` accept an absolute `deadline`
measured by the event-loop clock.

For low-level single-server use, the constructor is
`ConnectionPool(address, connection_factory)`: `address` is an `Address`, and
the factory is a zero-argument async callable returning an open, handshaken
`Connection`. Use the client factories for discovery and routing.

### Read preferences

```python
from kover import ReadPreference, from_uri

client = await from_uri(
    "mongodb://seed1:27017,seed2:27017/shop?replicaSet=rs0"
    "&readPreference=secondaryPreferred"
    "&readPreferenceTags=region:east&readPreferenceTags="
    "&maxStalenessSeconds=120&localThresholdMS=15"
)
try:
    orders = client.shop.orders
    documents = await (
        orders.find({})
        .read_preference(ReadPreference("nearest"))
        .to_list()
    )
    reply = await client.command(
        {"count": "orders"},
        db_name="shop",
        read_preference=ReadPreference("primary"),
    )
finally:
    await client.close()
```

Modes are `primary` (default), `primaryPreferred`, `secondary`,
`secondaryPreferred`, and `nearest`. Ordered tag sets are tried after staleness
filtering; `{}` is a catch-all. Max staleness is `-1` (disabled) or an integer
of at least 90 seconds. `primary` rejects nonempty tags and enabled staleness.
Tags/staleness do not constrain a preferred mode's primary fallback.

Eligible reads use the effective read preference; writes, unknown/admin
commands, and aggregations containing `$out` / `$merge` use primary routing.
Configure cursor overrides before execution. `getMore` and `killCursors`
retain server affinity, not socket affinity. Transactions require primary
reads and pin a server address, never a connection.

`directConnection=true` requires one non-SRV seed and keeps operations on it,
even if it is a secondary. Writes are not redirected; direct mode does not
make secondary transactions valid.

**Routing limitations:** Discovery is snapshot-based, not full SDAM. There is
no background monitoring, automatic retry after command failure, or automatic
failover guarantee. On-demand scans run when cached servers cannot satisfy an
operation; cached roles and staleness measurements can become outdated.
Recreate the client when a fresh topology view is needed. Load-balanced mode
is unsupported. URI parsing does not imply every parsed option is applied;
automatic retries and custom TLS certificate options are not implemented.

## Typed documents and BSON

`Document` extends Pydantic's `BaseModel` with `extra="forbid"`,
`use_enum_values=True`, and `serialize_by_alias=True`. MongoDB's `_id` is a
regular model field named `object_id`, with alias `_id` and default `None`.
`model_dump()` uses field aliases and omits `_id` when its value is `None`.

```python
from uuid import UUID, uuid4

from pydantic import Field

from kover import Document


class User(Document):
    username: str = Field(min_length=3, max_length=32)
    age: int = Field(ge=18)
    external_id: UUID = Field(default_factory=uuid4, alias="externalId")
```

Native UUIDs require an explicit BSON representation. Use this client for the
`User` schema and CRUD examples below:

```python
from bson import CodecOptions, UuidRepresentation

from kover import from_uri

client = await from_uri(
    "mongodb://127.0.0.1:27017/",
    codec_options=CodecOptions(
        uuid_representation=UuidRepresentation.STANDARD,
    ),
)
```

`make_client()` accepts the same `codec_options=` argument. `STANDARD` encodes
UUIDs as binary subtype 4 and decodes them back to `UUID`. The default
`UNSPECIFIED` representation rejects native UUID encoding.

| API | Purpose |
| --- | --- |
| `doc.model_dump()` | Python-mode dump using field aliases, including `_id` when set |
| `doc.model_dump(exclude={"object_id"})` | Dump without `_id`; exclusion uses the Python field name |
| `Model.model_validate(payload)` | Validate a MongoDB document, including its `_id` |
| `doc.object_id` / `doc.object_id = value` | Read or assign the document ID |
| `Model.model_mongodb_schema()` | Generate a `{"$jsonSchema": ...}` validator |

```python
from bson import ObjectId

user = User(username="alice", age=27)
assert user.object_id is None
assert "_id" not in user.model_dump()

identifier = ObjectId()
stored = User.model_validate({"_id": identifier, **user.model_dump()})
assert stored.object_id == identifier
assert stored.model_dump()["_id"] == identifier
```

Insert operations do not assign generated IDs back to the input model; assign
`user.object_id = await users.insert_one(user)` if needed. Field names are not
automatically converted to camelCase: declare aliases explicitly, as with
`externalId` above.
See [documents and serialization](docs/documents.md) for details.

Use Python-mode dumps for BSON, not `model_dump(mode="json")`. BSON's native
Pydantic integration preserves BSON instances in Python mode. Kover does not
globally patch BSON classes or `uuid.UUID`.

### Decimal values

Schema generation is not value conversion. A `decimal.Decimal` annotation
produces a `decimal` schema, but `model_dump()` retains the Python `Decimal`;
it needs a codec or explicit conversion for BSON encoding.

For domain models using `Decimal`, prefer the `DecimalCodec` example in the
[BSON README](https://github.com/megawattka/bson#custom-codecs) over manual
conversion or model serializers. Define that codec in your application and
register it with `CodecOptions(type_registry=TypeRegistry([DecimalCodec()]))`
(`CodecOptions` and `TypeRegistry` are imported from `bson.codec_options`).
Pass these options as `codec_options=` to `from_uri()` or `make_client()`;
if you also use UUIDs, include their representation in the same options.
The codec converts `Decimal` to BSON `Decimal128` on writes and back to
`Decimal` on reads, including values in nested documents. Values must still
fit the precision and range of Decimal128. `DecimalCodec` is an example to
define, not a built-in class to import.

Alternatively, use `bson.Decimal128` directly for stored values:

```python
from decimal import Decimal

from bson import Decimal128

from kover import Document


class Product(Document):
    price: Decimal128


product = Product(price=Decimal128(Decimal("19.99")))
payload = product.model_dump()
```

## MongoDB schema validation

```python
from kover import ValidationLevel

users = await client.demo.users.create_if_not_exists()
await users.set_validator(
    User.model_mongodb_schema(),
    level=ValidationLevel.STRICT,
)
user = User(username="alice", age=27)
alice_id = await users.insert_one(user)
```

The generator resolves references, normalizes JSON Schema, maps BSON types,
and checks MongoDB compatibility without mutating the input schemas.
Unsupported constraints raise `SchemaGenerationException`; there is no
permissive mode that silently removes validation rules.

The root `_id` is required and has `bsonType: "objectId"`, without a `null`
branch. `None` is only an application-side placeholder for an unset ID and is
excluded from dumps. Nested `Document` models also declare `_id`, but it is
optional in their schemas; plain Pydantic models do not inherit this field.

Examples of unsupported constraints include recursive/external references,
email/IP `format`, discriminators, constrained binary lengths, UUID versions,
datetime bounds/timezone constraints, and decimal digit/scale limits.
Custom Python validators are not translated into server-side rules.
Defaults are applied by Pydantic, not MongoDB; `default` annotations are omitted
from the server validator. MongoDB cannot enforce binary subtypes or UUID
contents through these schemas.

## CRUD and cursors

```python
from kover import Delete, Update

await users.insert_many([
    User(username="charlie", age=31),
    User(username="dana", age=24),
])
user: User | None = await users.find_one({"username": "charlie"}, cls=User)

cursor = (
    users.find({"age": {"$gte": 21}}, cls=User)
    .sort({"age": -1})
    .limit(50)
    .batch_size(25)
)
async with cursor:
    async for item in cursor:
        print(item.object_id, item.username)

all_users: list[User] = await users.find({}, cls=User).to_list()
await users.update(Update({"username": "charlie"}, {"$set": {"age": 32}}))
deleted = await users.delete(Delete({"username": "dana"}, limit=1))
```

Without `cls=`, queries return dictionaries. `insert_one()` returns an ID;
`insert_many()` returns a list of IDs. `update(*updates)` and `delete(*deletes)`
accept operation models as positional arguments. Use update operators such as
`$set` / `$inc`; deletion uses `limit=1` for one match or `limit=0` for all.

Cursors are lazy and support `sort`, `skip`, `limit`, `batch_size`, `projection`,
`hint`, `comment`, and `collation`. A projection used with `cls=Model` must retain
the fields required to validate that model. A cursor cannot be read concurrently
across tasks. Use `async with cursor:` when iteration may stop early to clean
up the server cursor. `to_list()` consumes remaining results; `first()` raises
`StopAsyncIteration` if empty. Close the cursor if you only consume its first item.

```python
stats = await users.aggregate([
    {"$group": {"_id": None, "count": {"$sum": 1}}},
]).to_list()
plan = await users.aggregate([{"$match": {"age": {"$gte": 18}}}], explain=True).command_result()
```

Aggregation returns a lazy cursor. For commands returning a document rather
than a cursor, such as aggregation explain, use `command_result()`.
Collection helpers also cover index management, collection options, and validators.

## Bulk writes

`BulkWriteBuilder` targets one or more `database.collection` namespaces using
MongoDB 8.0+'s server-level `bulkWrite` command. Execution and result fetching
are lazy; result cursors can require `getMore` round trips.

```python
from kover import BulkWriteBuilder, Delete, Update

builder = BulkWriteBuilder(ordered=True, errors_only=False)
builder.add_insert([{"sku": "A-1", "quantity": 5}], ns="demo.inventory")
builder.add_update(
    Update({"sku": "A-1"}, {"$set": {"quantity": 10}}),
    ns="demo.inventory",
)
builder.add_delete(Delete({"sku": "obsolete"}, limit=1), ns="demo.inventory")
results = await client.bulk_write(builder.build()).to_list()
```

## Sessions and transactions

Sessions and transactions are not context managers. Start transactions
synchronously; await commit/abort and explicitly end sessions.

```python
orders = await client.demo.orders.create_if_not_exists()
session = await client.start_session()
try:
    session.start_transaction()
    await orders.insert_one({"status": "created"}, session=session)
    await orders.insert_one({"status": "queued"}, session=session)
    await session.commit_transaction()
finally:
    try:
        await session.close()
    finally:
        await client.end_sessions([session])
```

- Pass the same session to every participating operation; it must belong to the same client.
- Reads require an effective `ReadPreference("primary")`. Override transaction read cursors if the client default is non-primary.
- `start_transaction(options=...)` stores options locally but does not apply them to commands.
- Empty transactions commit/abort locally without sending a transaction command.
- `session.close()` aborts an unfinished transaction and clears its server pin; it does not replace `end_sessions()`.
- There is no automatic transaction retry wrapper. Inspect `OperationFailure.is_transient_transaction_error` and `.is_unknown_commit_result` for application-controlled retries.
- An unknown commit result retains the transaction number and server pin for explicit commit retry. The cleanup example above does not implement retries.

See [Transactions](docs/transactions.md) before implementing production retry logic.

## GridFS

GridFS stores files as chunks, allowing files larger than MongoDB's 16 MiB
document limit. `put()` accepts `bytes`, `str`, `pathlib.Path`, or binary file objects.

```python
from kover import GridFS

fs = await GridFS(client.get_database("files")).indexed()
file_id = await fs.put(
    b"Hello from GridFS!",
    filename="hello.txt",
    metadata={"contentType": "text/plain"},
)
file_doc, content = await fs.get_by_file_id(file_id)
print(file_doc.filename, content.read())
await fs.delete(file_id)
```

SHA-1 is stored in metadata by default and verified on download when present.
Files can also be retrieved by filename, listed, and checked with `exists()`.

**Current limitation:** This is a buffered API, not a streaming API. Uploads
read the complete input into memory and build the chunks before writing.
Downloads load all chunks and assemble a complete `BytesIO`. Memory use grows
with file size and can exceed the payload size because of intermediate copies.
Local file reads are synchronous. Chunking avoids the BSON document limit,
not the client's memory limit.

**TODO:** Implement asynchronous chunk-by-chunk upload/download with bounded
buffers, incremental checksums, and nonblocking local file reads.

## Errors

- `OperationFailure`: MongoDB command/write failure, with `.code`, `.message`, `.code_name`, `.details`, `.err_info`, and `.error_labels`. Server error codes map to subclasses such as `DuplicateKey`.
- `ServerSelectionError`: no suitable server before the selection deadline, with per-server diagnostics.
- `PoolTimeoutError`: checkout, connection setup, or selection-lock deadline exceeded. `PoolClosedError` / `PoolPausedError` describe unavailable pools.
- `NetworkError` / `ProtocolError`: failed socket exchange or invalid server wire reply. Initial connection setup may also propagate `OSError`.
- `CredentialsException`: incomplete environment credentials.
- `SchemaGenerationException`: unsupported schema or constraint. Invalid model data raises Pydantic `ValidationError`.
- `GridFSFileNotFound` / `IncorrectGridFSData`: missing file or unsupported upload payload. A checksum mismatch raises `RuntimeError`.
- `ValueError` / `TypeError`: invalid configuration, session ownership, or operation use. BSON encoding errors are local errors, not MongoDB command failures.

For raw operations use `await client.command(document, db_name="demo")` or
`await client.demo.command(document)`. There is no `client.request()` API.

## Development

```bash
uv sync --dev
uv run pytest tests/unit tests/functional -q
KOVER_RUN_INTEGRATION=0 uv run pytest tests -q
uv run ruff check kover tests examples
uv run pyright kover tests examples
uv run python -m compileall -q kover tests examples
git diff --check
```

Unit tests include local TCP protocol tests but do not require MongoDB.
Integration tests are opt-in:

```bash
KOVER_RUN_INTEGRATION=1 MONGO_HOST=127.0.0.1 MONGO_PORT=27017 \
    uv run pytest tests/integration -v
```

Optional credentials use `MONGO_USER`, `MONGO_PASSWORD`, and `MONGO_AUTH_DB`.
The current test suite does not consume `MONGODB_URI`. Use a deployment
supporting the tested features, including transactions and MongoDB 8.0+ bulk writes.
Sharded tests are separately enabled by `KOVER_RUN_SHARDED=1`.

## Documentation and examples

- [Architecture](docs/architecture.md)
- [Documents, IDs, serialization, and schema validation](docs/documents.md)
- [Connections, authentication, pools, and deadlines](docs/connections.md)
- [Read preferences and routing limits](docs/read_preferences.md)
- [Transactions and session lifecycle](docs/transactions.md)
- [Development and integration configuration](docs/development.md)
- [Runnable examples](examples/): schemas, CRUD, bulk writes, transactions, read preferences, and GridFS.

Bug reports and contributions are welcome via [GitHub Issues](https://github.com/megawattka/kover/issues)
and pull requests. Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE). Copyright (c) 2024–present megawattka.