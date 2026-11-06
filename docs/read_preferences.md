# Read preferences

Read preference controls **where eligible reads run**, not write
acknowledgement or read isolation. Secondary reads can be stale. Use read
concern/write concern separately when the application needs consistency
guarantees; choosing `nearest` is not a consistency guarantee.

## Modes

| Mode | Replica-set selection |
| --- | --- |
| `primary` | Primary only; default |
| `primaryPreferred` | Primary if present; otherwise matching secondaries |
| `secondary` | Matching secondaries only; no primary fallback |
| `secondaryPreferred` | Matching secondaries if available; otherwise primary |
| `nearest` | Eligible primary and secondaries, subject to tags and RTT window |

After eligibility filtering Kover chooses randomly among servers whose measured
RTT is at most `fastest RTT + local_threshold` (default: 0.015 seconds).
`nearest` does not always choose the single fastest server or a specific region.

Mongos servers are selected as routers, and `$readPreference` metadata delegates
read routing to them. A single standalone server can be selected regardless of
preference, but there are no replicas to route reads to. Direct connections
likewise select a fixed address; see [connections](connections.md).

## Client default

```python
from typing import Any

from kover import ReadPreference, make_client


async def read_items() -> list[dict[str, Any]]:
    client = await make_client(
        replica_set="rs0",
        read_preference=ReadPreference(mode="secondaryPreferred"),
    )
    async with client:
        async with client.shop.items.find().limit(10) as cursor:
            return await cursor.to_list()
```

The factory performs initial selection using the configured preference. A
`secondary` default can therefore fail during client construction if no eligible
secondary exists, even if a primary is reachable.

A URI can specify the same settings:

```text
mongodb://db1,db2/?replicaSet=rs0&readPreference=secondaryPreferred
```

## Per-cursor and per-command overrides

```python
from typing import Any

from kover import Kover, ReadPreference


async def report(client: Kover) -> list[dict[str, Any]]:
    policy = ReadPreference(mode="nearest")
    async with (
        client.shop.items.find({"active": True})
        .read_preference(policy)
        .limit(10)
    ) as cursor:
        return await cursor.to_list()


async def count_on_primary(client: Kover) -> dict[str, Any]:
    return await client.command(
        {"count": "items", "query": {"active": True}},
        db_name="shop",
        read_preference=ReadPreference(mode="primary"),
    )
```

`find()` and `aggregate()` return lazy cursors. Set `.read_preference(...)`
before the cursor starts; changing it after iteration starts or after close
raises `RuntimeError`. `find_one()` has no read-preference argument: use the
client default or `find(...).read_preference(...).limit(1).to_list()`.

The initial command selects the server. Later `getMore`/`killCursors` use the
same server address, not a newly selected secondary. A cursor does not hold a
connection between batches. Close cursors when stopping iteration early.

## Ordered tags and max staleness

```python
from kover import ReadPreference

policy = ReadPreference(
    mode="secondary",
    tag_sets=({"region": "eu", "usage": "analytics"}, {"region": "eu"}, {}),
    max_staleness_seconds=120,
)
```

Tag sets are tried **in order**, stopping at the first set with matches. All
key/value pairs in a set must match. `{}` matches any otherwise eligible server;
omit it to prohibit a generic fallback. Tags refer to replica-set member tags
configured in MongoDB, not document fields.

`max_staleness_seconds=-1` disables staleness filtering. An enabled value must
be at least 90 seconds. Kover estimates secondary staleness from snapshot
last-write/update times, including a 10-second heartbeat allowance. Without a
primary it compares secondary last-write times. It excludes secondaries with
missing required last-write information. This is an estimate, not a guarantee
of application-visible freshness, especially without background monitoring.

`primary` rejects nonempty `tag_sets` and enabled max staleness during model
validation. `primaryPreferred` ignores tag/staleness constraints while a primary
is available. `secondaryPreferred` falls back to a primary when no secondary
matches, even if tags were supplied. Use `secondary` when primary fallback must
be prohibited.

URI equivalent with an ordered fallback:

```text
mongodb://db1,db2/?replicaSet=rs0&readPreference=secondary&readPreferenceTags=region:eu&readPreferenceTags=&maxStalenessSeconds=120
```

## Which commands use the preference?

The current classifier permits non-primary routing for `find`, `count`,
`distinct`, read-only `aggregate`, and `explain` wrapping an eligible read.
Aggregation containing `$out` or `$merge` is routed as a write. Writes and
unknown/admin commands, including `ping`, use primary policy. Keep the command
name as the first key when calling `client.command()`.

An override on a write does not route it to a secondary. Raw `$readPreference`
in the document is not an override: preparation removes it and builds metadata
from `ReadPreference` instead. Standalone commands omit this metadata.

Transactions require `primary` reads. A non-primary default must be overridden
for transactional reads, for example with
`.read_preference(ReadPreference(mode="primary"))` on the cursor. Otherwise
Kover raises `ValueError` before dispatch. See [transactions](transactions.md).

## Availability and example

Selection uses cached snapshots and refreshes discovery when no eligible cached
server remains. There is no background monitor or automatic command retry.
`ServerSelectionError` means selection exceeded its deadline; verify member
addresses, replica-set name, available roles, tags, and staleness constraints.

The read-only [example](../examples/read_preferences.py) demonstrates every
mode, tags/staleness, and a command override:

```bash
python -m examples.read_preferences
# To observe actual secondary routing, use a reachable replica set:
MONGODB_URI='mongodb://db1,db2/?replicaSet=rs0&serverSelectionTimeoutMS=3000' \
  python -m examples.read_preferences
```

The script reads `kover_examples.items` by default and never writes documents.
Set `MONGO_DATABASE` and `MONGO_COLLECTION` to read existing data. Without a URI,
it accepts the host/port/authentication environment variables described in
[connections](connections.md). URI credentials take precedence by using the URI
path exclusively; the script does not merge environment credentials into it.