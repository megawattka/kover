# Server Discovery and Monitoring (SDAM)

Kover performs initial seed discovery and then continuously monitors the known
deployment. SDAM is responsible for the driver's view of servers and topology;
server selection uses that view to choose an address for each operation.

## Lifecycle

`make_client()` and `from_uri()` construct the discovery, monitor, selector,
pool registry, and executor. Before returning, they wait for an eligible server
according to the configured read preference. The monitor starts during that
selection and runs in the same asyncio event loop as the client:

```python
from kover import from_uri


async def main() -> None:
    client = await from_uri(
        "mongodb://db1:27017,db2:27017/?replicaSet=rs0",
    )
    async with client:
        await client.admin.ping()
```

`await client.close()` first stops monitor tasks and then closes application
pools. The async context manager is preferred for normal application code.

## Topology state

The monitor publishes snapshots through `TopologyState`. Each server
description contains its address, validated `hello` response, round-trip time,
update time, and availability metadata. The server role is derived from the
description.

The topology recognizes these deployment views:

| Topology | Meaning |
| --- | --- |
| `Unknown` | No usable role has been observed yet |
| `Single` | Direct connection or one standalone server |
| `Sharded` | One or more `mongos` routers |
| `ReplicaSetNoPrimary` | Replica-set members are known, but no primary is known |
| `ReplicaSetWithPrimary` | A current primary is known |

Unavailable servers remain in the snapshot as `ServerType.UNKNOWN`. Their
`last_error` is retained for diagnostics and their addresses remain candidates
for reconnection. They are excluded from server selection until a successful
heartbeat restores their role.

For replica sets, membership comes from the `hosts`, `passives`, and `arbiters`
fields in `hello`. Without a known primary, Kover can add members based on
non-primary replies. A current primary determines membership and can remove
addresses. When a new primary is observed, the previous primary becomes
`Unknown` if it is still a member.

## Heartbeats

Each known address has a dedicated heartbeat connection independent of the
application pool. In streaming mode a second monitoring connection measures
RTT without counting the time spent waiting for topology changes. Each client
allows up to ten concurrent monitoring handshakes.

The default heartbeat interval is 10 seconds and the minimum is 500 ms:

```python
from kover import make_client


async def connect() -> None:
    client = await make_client(
        host="db1",
        heartbeat_frequency=5.0,
        server_monitoring_mode="auto",
    )
    async with client:
        await client.admin.ping()
```

The URI equivalents are `heartbeatFrequencyMS` and `serverMonitoringMode`.
URI durations are in milliseconds; Python arguments use seconds. Monitor
checks use `connect_timeout` as their base timeout (10 seconds when set to
`None`), plus the heartbeat interval for awaitable `hello`.

## Monitoring modes

`server_monitoring_mode` accepts three values:

| Mode | Behavior |
| --- | --- |
| `auto` | Streaming monitoring outside FaaS; polling in FaaS |
| `poll` | Regular `hello` at the heartbeat interval |
| `stream` | Awaitable `hello` when supported, polling fallback otherwise |

Streaming monitoring uses the latest `topologyVersion` and sends
`maxAwaitTimeMS`. The server holds the request until a significant topology
change or the await period expires, and can keep sending replies without a new
request. If the server does not advertise `topologyVersion`, the worker uses
regular polling for that server.

FaaS detection follows common runtime environment variables such as AWS
Lambda, Google Cloud Functions, Cloud Run, Azure Functions, and Vercel. Polling
is preferred there because a long-lived streaming monitor is not a good fit for
short-lived invocations.

## Failures and recovery

When a heartbeat fails, Kover retires the affected pool, marks the server
`Unknown`, and notifies waiting selectors of that change. The monitor
reconnects with bounded exponential backoff and updates the topology again
when a later check succeeds. Removing a server from the topology also retires
its pool.

Applicable application transport errors also retire the pool and request a
fresh check. A role-change error with a stale or equal `topologyVersion` is
ignored for SDAM. Other role-change errors request a check, but retire the pool
only for shutdown errors or a server with wire version below 8 (MongoDB 4.2).
On retirement, idle connections close and leased ones close when returned. An
error from a retired pool cannot invalidate its replacement.

SDAM changes server eligibility but does not replay the failed command. Kover
does not implement transparent retryable reads, retryable writes, or automatic
transaction retry wrappers. Applications must decide whether an operation is
safe to retry.

## Selection interaction

Selection first evaluates the current snapshot. If there is no eligible server,
it requests an earlier check and waits for a topology publication until
`server_selection_timeout` expires (or the operation deadline, if sooner).
Read preference, tags, max staleness, and the local RTT threshold are applied
to each new snapshot. A recovered primary or elected primary can therefore be
selected as soon as its heartbeat is published.

Cursor `getMore` and `killCursors` retain server-address affinity. Transactions
pin a server address, not a physical connection; an application should handle
the resulting error if the pinned server becomes unavailable.