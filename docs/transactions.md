# Sessions and transactions

MongoDB multi-document transactions require a replica set or a suitable sharded
deployment; a standalone server is not enough. Server-version and command
restrictions still apply. Use normal discovery and `primary` read preference,
not a direct connection to a secondary.

## Explicit lifecycle

`await client.start_session()` sends `startSession` and returns a `Session`.
`session.start_transaction()` is synchronous: it only changes local state.
Always pass `session=session` to every operation intended to participate.

```python
import asyncio
import os
from uuid import uuid4

from kover import from_uri


async def main() -> None:
    client = await from_uri(os.environ["MONGODB_URI"])
    async with client:
        # Provision collections outside the transaction.
        collection = await client.shop.events.create_if_not_exists()
        session = await client.start_session()
        try:
            session.start_transaction()
            try:
                await collection.insert_one(
                    {"_id": uuid4().hex, "kind": "created"},
                    session=session,
                )
                await collection.insert_one(
                    {"_id": uuid4().hex, "kind": "confirmed"},
                    session=session,
                )
            except (Exception, asyncio.CancelledError):
                await session.abort_transaction()
                raise
            else:
                await session.commit_transaction()
        finally:
            await session.close()


asyncio.run(main())
```

This is a basic explicit-lifecycle example, not an automatic retry wrapper.
Abort/close are network operations and can themselves fail. Production error
handling should preserve the original operation error if cleanup fails, and
decide how to handle an unknown commit result **before** closing the session.
Do not blindly replay this function after a network error: the server may have
already committed it.

Sessions currently have no async context manager or transaction callback helper.
Use `try/finally` for ownership and explicit commit/abort. Closing the client is
not a substitute for closing its application sessions.

## State and metadata

| State | Meaning |
| --- | --- |
| `NONE` | No transaction has been started |
| `STARTING` | Started locally; first command not yet acknowledged |
| `IN_PROGRESS` | The server accepted the first transaction command |
| `COMMITTING` | Commit is in progress or its outcome is unresolved |
| `COMMITTED` | Commit returned successfully |
| `ABORTED` | Aborted or a non-unknown commit failure ended the transaction |

The first transaction has `txnNumber=0`; every new transaction increments it.
The executor adds `lsid`, `txnNumber`, and `autocommit=false`. While state is
`STARTING`, it also adds `startTransaction=true`. State changes to `IN_PROGRESS`
only after the first command succeeds. The driver does not retry that command
automatically if it fails.

A transaction pins a **server address**, not a connection. Every command still
checks out a pooled connection. Cursor continuations retain their server
affinity. Commit/abort retain the same transaction number and pinned address
until the transaction ends.

An operation using a session from another client is rejected. A session supports
one active transaction at a time; do not use the same session concurrently in
multiple tasks. It can start another transaction after commit or abort.

## Read preference and options

Transactional reads must use `primary`. With a non-primary client default,
override it for each transactional read:

```python
from typing import Any

from kover import Kover, ReadPreference, Session


async def read_in_transaction(
    client: Kover, session: Session,
) -> list[dict[str, Any]]:
    async with (
        client.shop.events.find({}, session=session)
        .read_preference(ReadPreference(mode="primary"))
    ) as cursor:
        return await cursor.to_list()
```

Writes use primary routing. Read-preference metadata and per-command write
concern are not attached to transactional commands. Passing a non-primary read
policy raises `ValueError` before dispatch.

`start_transaction(options=...)` currently stores its options locally but does
**not** apply them to commands. Do not assume that supplying a dict configures
transaction read concern, write concern, or commit timeouts. There is no
`with_transaction` or automatic transaction retry API.

## Commit failures and retries

`commit_transaction(deadline=...)` accepts an absolute event-loop deadline.
A successful commit moves to `COMMITTED` and unpins the server. Calling commit
again in `COMMITTED` is a no-op.

`OperationFailure` exposes MongoDB labels:

- `is_transient_transaction_error` checks `TransientTransactionError`.
- `is_unknown_commit_result` checks `UnknownTransactionCommitResult`.
- `has_label(name)` tests another label.

On an unknown-commit-result `OperationFailure`, state remains `COMMITTING` and
the address remains pinned. Calling `commit_transaction()` again uses the same
transaction number. The driver does not perform that retry for you. Apply an
application deadline and retry policy rather than looping indefinitely.

Other commit `OperationFailure` errors move to `ABORTED` and clear the pin.
Network errors during commit also propagate; `COMMITTING` can remain active.
A network failure is not proof of rollback. Determine the outcome or follow
MongoDB's transaction retry guidance before retrying application writes.

## Abort and close

`abort_transaction()` accepts an optional absolute deadline. It suppresses
MongoDB error 251 (`NoSuchTransaction`), since the server may already have
aborted a failed transaction. Other failures propagate. Its cleanup always sets
local state to `ABORTED` and removes the server pin; that local state alone does
not prove the server received the abort.

Calling abort again in `ABORTED` is a no-op. `Session.close()` aborts locally
active or `COMMITTING` transactions and clears pinning. It does not currently
send `endSessions` or make the object permanently unusable. Do not close an
unresolved commit before applying a desired commit-retry policy.

See [architecture](architecture.md) for metadata preparation and ownership,
and [connections](connections.md) for connection and timeout behavior.