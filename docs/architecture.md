# Architecture

Kover is a Python 3.12+ `asyncio` MongoDB driver. It uses asyncio streams for
network I/O, Pydantic v2 for models, and PyMongo's BSON and URI utilities.
Application commands are not delegated to a PyMongo client or a thread pool.

See [connections](connections.md) for configuration,
[read preferences](read_preferences.md) for routing,
[transactions](transactions.md) for session state, and
[development](development.md) for tests and contributor commands.

## Layers and responsibilities

| Layer | Main components | Responsibility |
| --- | --- | --- |
| Public API | `Kover`, `Database`, `Collection`, `Cursor`, `Session` | User-facing operations, lazy iteration, logical session state |
| Composition | `bootstrap.make_client`, `bootstrap.from_uri` | Validate configuration, construct dependencies, perform initial selection |
| Execution | `CommandExecutor`, router, preparation | Resolve a server, copy and prepare commands, apply metadata, execute |
| Policies | `policies.commands`, `policies.routing` | Classify reads/writes and enforce routing rules |
| Topology | `ServerDiscovery`, `ServerSelector`, `TopologyState` | Probe servers, publish snapshots, choose eligible addresses |
| Pooling | `PoolRegistry`, `ConnectionPool`, `ConnectionLease` | Lazily create per-server pools and grant exclusive connections |
| Connections | `ConnectionFactory`, `Connection`, `ServerProbe` | Connect, handshake, authenticate, exchange commands |
| Wire and transport | codec, handshake, error mapper, `Transport` | BSON framing, compression, reply validation, TCP/TLS bytes |
| Documents | `Document`, schema generator | Model serialization and MongoDB `$jsonSchema` generation |

## Client construction

```text
make_client(...) / from_uri(...)
  -> ConnectionFactory
  -> ServerProbe -> ServerDiscovery -> ServerSelector
  -> PoolRegistry
  -> CommandExecutor
  -> initial server selection
  -> Kover
```

Construction is asynchronous: the factory verifies that a suitable server can
be discovered before returning a client. Discovery uses temporary connections
which are closed after probing. Application connections are opened lazily when
commands check out a connection from a server pool. Initial selection failure
also closes the composed executor.

`Kover(executor)` is the injection boundary for custom composition and unit
tests. It does not accept host/port configuration itself. The client owns its
injected executor: closing the client closes that executor and its pools.

## One operation, end to end

```text
Collection / Database / Kover.command
  -> CommandExecutor.execute
  -> router: cursor affinity, transaction pin, or server selection
  -> preparation: copied document + routing/session/write concern metadata
  -> PoolRegistry.for_server(address)
  -> ConnectionPool.execute -> acquire ConnectionLease
  -> Connection.command -> codec -> Transport -> MongoDB
  -> reply validation / error mapping
  -> release lease (discard unusable connection)
```

The original command document is not modified by command preparation. Supplied
`$readPreference` is removed and regenerated from the effective routing policy.
Write concern is added only to supported commands outside transactions.

Successful command replies carry the selected server address internally in a
dict-compatible `CommandReply`. Cursors use it to retain server affinity for
`getMore` and `killCursors` without retaining a socket.

## Server snapshots

Discovery starts from configured seeds and follows advertised replica-set
members. Selection first checks its current snapshot. With no eligible cached
candidate it serializes refreshes under a lock and invokes discovery until a
candidate appears or the selection deadline expires. A complete snapshot
replaces the old one rather than being mutated while it is being selected.

Eligible servers are filtered by role, read preference, tags, and staleness.
Selection then chooses randomly within an RTT window of the fastest eligible
server. For mongos deployments the router is selected locally; read-preference
metadata tells mongos how to route the read.

The executor invalidates a cached server description on network/protocol/time
failures and server errors indicating a role change. It does **not** retry the
failed operation. Other eligible cached servers may still be selected without
a new scan. There is no continuous topology monitoring or transparent failover
and replay guarantee.

## Resource ownership and concurrency

- A `PoolRegistry` owns one bounded pool per server address.
- A pool owns idle and checked-out connections and reserves capacity while a
  connection is being created. A lease has exclusive use of one connection.
- A `Session` owns logical transaction state and a server pin, not a socket.
- A `Cursor` owns buffered results and server cursor identity. It is lazy:
  constructing `find()` or `aggregate()` does not issue a command.
- Cursor operations must not run concurrently on the same cursor. Do not
  concurrently mutate or use one transaction session either.
- Closing a client closes idle pool connections. Checked-out connections are
  closed when returned. Finish application tasks before shutting down clients.

## Extension and test boundaries

Protocols in `execution/protocols.py` and `topology/protocols.py` separate
execution from I/O. Tests can inject an executor, pool provider, discovery
adapter, or probe without a MongoDB deployment. Functional tests additionally
exercise the actual wire stack against local asyncio TCP servers.

The pure routing/classification functions are tested separately from network
behavior. Keep transport code unaware of sessions, database helpers, and
selection policy; keep API helpers unaware of sockets and pool bookkeeping.