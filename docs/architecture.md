# Architecture

Kover is a Python 3.12+ `asyncio` MongoDB driver. It uses asyncio streams for
network I/O, Pydantic v2 for models, Elune for BSON serialization, and
its own URI parser with asynchronous dnspython SRV/TXT discovery.
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
| Topology | `ServerDiscovery`, `TopologyMonitor`, `Topology`, `ServerSelector`, `TopologyState` | Discover members, monitor heartbeats, apply SDAM transitions, publish snapshots, choose eligible addresses |
| Pooling | `PoolRegistry`, `ConnectionPool`, `ConnectionLease` | Lazily create per-server pools and grant exclusive connections |
| Connections | `ConnectionFactory`, `Connection`, `ServerProbe` | Connect, handshake, authenticate, exchange commands |
| Wire and transport | codec, handshake, error mapper, `Transport` | BSON framing, compression, reply validation, TCP/TLS bytes |
| Documents | `Document`, schema generator | Model serialization and MongoDB `$jsonSchema` generation |

`Document` uses Pydantic's `model_validate()` and `model_dump()` directly.
Its regular `object_id` field accepts MongoDB's `_id` alias; dumps use aliases
by default and omit an unset ID. Collection reads with `cls=Model` validate
results through `Model.model_validate()`. Inserts serialize a copy and do not
assign generated IDs back to the model. See [documents](documents.md) for the
serialization and schema contracts.

## Client construction

```text
make_client(...) / from_uri(...)
  -> ConnectionFactory
  -> PoolRegistry (application connections)
  -> TopologyMonitor -> TopologyState -> ServerSelector
  -> CommandExecutor
  -> initial selection starts monitoring and waits for an eligible server
  -> Kover
```

Construction is asynchronous: the monitor starts with the configured seeds
and publishes topology updates while the factory waits for a suitable server.
The monitor owns its own connections. Application connections open lazily on
checkout. If initial selection fails or is cancelled, the executor shuts down
the monitor and pools.

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

## SDAM topology and server snapshots

`TopologyMonitor` runs one worker per known address. Each worker starts with a
handshake, then performs regular or awaitable `hello` checks on a dedicated
connection. `TopologyState` publishes server descriptions as a new tuple
rather than mutating the previous snapshot in place. `ServerDiscovery.scan()`
remains available for one-shot discovery without a live monitor.

`Topology` applies SDAM transitions synchronously before publication. It tracks
single-server, sharded, replica-set-with-primary, and replica-set-without-primary
topology kinds; validates replica-set names; detects stale topology versions and
primaries; adds advertised members; and removes members no longer advertised.
Temporary failures do not erase addresses: the last description is retained as
`Unknown` with the latest error so the worker can reconnect.

Eligible servers are filtered by role, read preference, tags, and staleness.
Selection then chooses randomly within an RTT window of the fastest eligible
server. For mongos deployments the router is selected locally; read-preference
metadata tells mongos how to route the read.

Topology publications wake server-selection waiters, so a newly elected primary
or recovered secondary can become eligible without waiting for the selection
timeout. Application network/topology errors also request an immediate monitor
refresh. The executor does **not** retry the failed operation: SDAM changes
server eligibility, but command replay is an application-level decision.

See [SDAM and server monitoring](sdam.md) for monitoring modes, heartbeat
configuration, pool generations, and shutdown behavior.

Both command and monitor replies pass through `CommandCodec.decode()`. By
default it returns the reply document and rejects the `moreToCome` flag.
Streaming monitoring calls `decode(..., exhaustive=False)` to receive
`(document, message_id, more_to_come)` and validate each subsequent response
against the preceding server message ID.

## Resource ownership and concurrency

- A `PoolRegistry` owns one bounded pool per server address.
- A pool owns idle and checked-out connections and reserves capacity while a
  connection is being created. A lease has exclusive use of one connection.
- A `Session` owns logical transaction state and a server pin, not a socket.
- A `Cursor` owns buffered results and server cursor identity. It is lazy:
  constructing `find()` or `aggregate()` does not issue a command.
- Cursor operations must not run concurrently on the same cursor. Do not
  concurrently mutate or use one transaction session either.
- Closing a client stops the monitors before closing idle pool connections.
  Checked-out connections close when returned. Finish application tasks before
  shutting down clients.

## Extension and test boundaries

Protocols in `execution/protocols.py` and `topology/protocols.py` separate
execution from I/O. Tests can inject an executor, pool provider, discovery
adapter, or probe without a MongoDB deployment. Functional tests additionally
exercise the actual wire stack against local asyncio TCP servers.

The pure routing/classification functions are tested separately from network
behavior. Keep transport code unaware of sessions, database helpers, and
selection policy; keep API helpers unaware of sockets and pool bookkeeping.