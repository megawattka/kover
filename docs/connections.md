# Connections

Use `make_client()` for explicit parameters or `from_uri()` for MongoDB URI
configuration. Both are asynchronous and perform initial server selection.
Keep clients alive across operations and always close them.

## Explicit configuration

```python
import asyncio
import os

from kover import AuthCredentials, ReadPreference, make_client


async def main() -> None:
    client = await make_client(
        host=os.environ.get("MONGO_HOST", "127.0.0.1"),
        port=int(os.environ.get("MONGO_PORT", "27017")),
        credentials=AuthCredentials.from_environ(),
        read_preference=ReadPreference(mode="primary"),
        server_selection_timeout=5.0,
        connect_timeout=2.0,
        max_pool_size=20,
    )
    async with client:
        await client.admin.ping()


asyncio.run(main())
```

`MONGO_HOST` and `MONGO_PORT` above are read by the example, not implicitly by
`make_client()`. Without arguments the factory uses `127.0.0.1:27017`.

| Parameter | Default | Meaning |
| --- | --- | --- |
| `replica_set` | `None` | Expected replica-set name; reject mismatched members |
| `direct_connection` | `False` | Probe and use only the configured seed |
| `read_preference` | `ReadPreference()` | Default read policy (`primary`) |
| `server_selection_timeout` | `30.0` | Selection timeout in seconds |
| `connect_timeout` | `10.0` | Per-probe/application connection setup limit in seconds; `None` disables the application setup limit |
| `local_threshold` | `0.015` | RTT eligibility window in seconds |
| `max_pool_size` | `100` | Maximum connections **per server**, including creation reservations |
| `tls` | `False` | Use TLS with the default validating SSL context |
| `compression` | `None` | Offered compressors, for example `("zlib",)` |
| `zlib_compression_level` | `-1` | Zlib level: `-1` uses the default, `0` to `9` selects the level |
| `application` | `None` | Client application metadata, for example `{"name": "worker"}` |
| `w` | `"majority"` | Default write acknowledgement policy |
| `write_concern` | `None` | Explicit `WriteConcern`, taking precedence over `w` |

Selection timeout must be finite and nonnegative; connection timeout must be
finite and positive or `None`. Discovery currently uses a 30-second per-probe
fallback when `connect_timeout=None`, still bounded by the scan/selection
deadline. Connection setup includes TCP/TLS, hello, and authentication.

## MongoDB URIs

```python
import asyncio
import os

from kover import from_uri


async def main() -> None:
    client = await from_uri(os.environ["MONGODB_URI"])
    async with client:
        await client.admin.ping()


asyncio.run(main())
```

For a replica set, configure reachable seed addresses, for example:

```text
mongodb://db1:27017,db2:27017/?replicaSet=rs0&serverSelectionTimeoutMS=5000
```

The composition layer consumes seeds, credentials, `replicaSet`,
`directConnection`, `readPreference`, repeated `readPreferenceTags`,
`maxStalenessSeconds`, `serverSelectionTimeoutMS`, `connectTimeoutMS`,
`localThresholdMS`, `maxPoolSize`, `tls`, `compressors`, `zlibCompressionLevel`, `appName`, `w`,
`journal`, and `wTimeoutMS`. A parsed URI is **not** a promise that every
recognized URI option is applied by Kover; inspect `bootstrap.from_uri()` for
the supported mapping. `loadBalanced=true` is explicitly rejected.

Kover parses URIs itself, without PyMongo. It supports multiple TCP seeds,
bracketed IPv6, percent-encoded credentials, and `mongodb+srv://` discovery
through asynchronous dnspython SRV/TXT queries. SRV targets must belong to the
seed's parent domain; TXT can supply `authSource`, `replicaSet`, and
`loadBalanced`, with explicit URI options taking precedence. SRV enables TLS
by default unless `tls=false` (or `ssl=false`) is specified. `srvServiceName`
selects the DNS service and `srvMaxHosts` limits the initial random seed set;
there is no periodic DNS refresh.

Option names are case-insensitive and `ssl` aliases `tls`. Unknown options,
duplicate scalar options (including aliases), malformed values, conflicting
settings, URI fragments, and Unix domain sockets raise `ValueError`.
`readPreferenceTags` may repeat, preserving order. Options use either `&` or
`;` separators, not both. Passwords and usernames must percent-encode reserved
URI characters. A username without a password is treated as an empty password.
Recognizing an `authMechanism` does not add support for that authentication
protocol: Kover's authentication layer still implements only SCRAM.

URI selection/connection timeouts are written in milliseconds and normalized
internally to seconds. `connectTimeoutMS=0` maps to `None`. Write concern
`wTimeoutMS` stays in milliseconds. A database path in a URI does not create a
default database accessor: use `client.get_database("name")` explicitly.

Percent-encode special characters in URI credentials. Prefer environment
variables or a secret manager over checked-in credentials; never log full
authenticated URIs.

## Authentication, TLS, compression

`AuthCredentials.from_environ()` reads:

| Variable | Meaning |
| --- | --- |
| `MONGO_USER` | Username |
| `MONGO_PASSWORD` | Password |
| `MONGO_AUTH_DB` | Authentication database, default `admin` |

If neither username nor password is set, it returns `None`. If only one is set,
it raises `CredentialsException`. Pass the result as `credentials=` explicitly.
URI authentication is resolved from the URI separately.

The authentication layer implements SCRAM-SHA-1 and SCRAM-SHA-256. TLS uses
`ssl.create_default_context()` with hostname verification; the public factory
does not expose a custom SSL context or client certificate configuration.

Compression is negotiated at hello. `zlib` uses the standard library; Snappy
and Zstandard need the `snappy` and `zstd` package extras respectively:

```bash
python -m pip install 'kover[snappy,zstd]'
```

Set `zlib_compression_level=9` with `compression=("zlib",)` in `make_client()`,
or use `?compressors=zlib&zlibCompressionLevel=9` in a MongoDB URI.
The default is `-1` (zlib's default); `0` disables compression within the zlib
stream and `1` through `9` select increasing compression levels.

## Replica sets and direct connections

In normal mode discovery follows advertised members. Their advertised hostnames
and ports must be reachable from the application, not merely from other MongoDB
containers. A common source of selection timeouts is a seed reachable on a
mapped port while advertised replica-set addresses are unreachable.

`direct_connection=True` (URI: `directConnection=true`) requires exactly one
seed. It ignores server role for address selection and never switches to a
different member. Eligible reads to a directly connected non-mongos server use
`primaryPreferred` metadata when the requested policy is `primary`, allowing
reads from a secondary. This does **not** make secondary writes or transactions
legal. Use normal replica-set discovery for primary routing and availability.

## Pools and deadlines

Application pools are created lazily per selected server. Every command checks
out an exclusive connection and returns it after the reply. Unusable
connections are discarded; a server command rejection alone does not make a
healthy connection unusable.

`max_pool_size` is not a global client limit. With multiple selected servers,
each has its own pool, in addition to temporary discovery connections.

`client.command(..., deadline=...)` takes an **absolute event-loop clock**
deadline, not seconds from now or a Unix timestamp:

```python
import asyncio

from kover import Kover


async def bounded_ping(client: Kover) -> None:
    deadline = asyncio.get_running_loop().time() + 2.0
    await client.command({"ping": 1}, deadline=deadline)
```

The deadline bounds selection waiting, pool-capacity waiting, connection setup,
and wire exchange. New connection setup also uses `connect_timeout` when set.
Selection has its own `server_selection_timeout`. A connection setup timeout
is not an idle-pool wait timeout or a default command execution timeout.
For helpers without a `deadline` parameter, use `asyncio.timeout()` around the
operation. MongoDB `maxTimeMS` limits server work and is a separate mechanism.

## Errors and shutdown

- `ServerSelectionError`: no eligible server before the selection deadline.
- `PoolTimeoutError`: connection checkout/setup could not complete as allowed.
- `PoolClosedError`: work was submitted to a closed pool/registry.
- `OSError`, `NetworkError`, `TimeoutError`: transport/setup/exchange failures.
- `ProtocolError`: malformed wire response.
- `OperationFailure`: MongoDB rejected a command; inspect `code` and labels.

The executor invalidates failed server descriptions for relevant network and
topology failures but does not automatically retry a command. See
[architecture](architecture.md) for snapshot refresh behavior.

Use `async with client` or `await client.close()`. Stop and await concurrent
operations before closing. Idle connections close immediately; checked-out
connections close when returned. Do not share clients across processes or
event loops; create them inside the async application using them.