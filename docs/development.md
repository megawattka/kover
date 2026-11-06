# Development

See [architecture](architecture.md) before changing ownership, routing, or
network code. The project targets Python 3.12+, uses Pydantic v2 and asyncio,
and configures strict Pyright and Ruff in `pyproject.toml`.

## Environment

From the repository root:

```bash
uv sync --dev
uv run python --version
```

`uv.lock` records the dependency resolution. To use an existing lock without
updating it, use `uv sync --dev --frozen`. Optional compressor dependencies can
be installed with `uv sync --dev --extra snappy --extra zstd`.

An alternative using a virtual environment and the declared development group
(requires a pip version supporting `--group`):

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e . --group dev
```

Use the project's declared dependencies; do not add a new test/type-check tool
just to run a local check. The commands below use `uv run`; the equivalent
commands work directly inside an activated development environment.

## Tests without MongoDB

```bash
uv run pytest tests/unit tests/functional -q
```

- `tests/unit/api`: API, cursor and session behavior with injected executors.
- `tests/unit/execution`: composition, routing and command preparation.
- `tests/unit/topology`: selection and discovery snapshots.
- `tests/unit/network`: transport, codec, authentication and pool lifecycle.
- `tests/unit/models`, `configuration`, `schema`: validation and pure helpers.
- `tests/functional`: actual wire exchanges against local asyncio TCP servers.

Functional tests do not need MongoDB but do require permission to open local
listening sockets. pytest-asyncio uses `asyncio_mode="auto"`; async pytest
tests do not need individual asyncio markers.

Run the complete suite with live integration explicitly disabled:

```bash
KOVER_RUN_INTEGRATION=0 KOVER_RUN_SHARDED=0 uv run pytest tests -q
```

Integration tests should report skips, not silently connect to a developer's
database. Run a focused group while investigating a failure:

```bash
uv run pytest tests/unit/topology/test_selector.py -q --tb=short
uv run pytest tests/unit/network/test_pool.py -v --tb=long
uv run pytest tests/unit/execution/test_bootstrap.py -q
```

## Integration tests

Use an isolated, disposable MongoDB deployment. These tests create and drop
databases/collections and may perform administrative operations; do not point
them at production or a shared database.

```bash
export KOVER_RUN_INTEGRATION=1
export MONGO_HOST=127.0.0.1
export MONGO_PORT=27017
# If authentication is enabled, set both using your secret source:
# MONGO_USER, MONGO_PASSWORD
export MONGO_AUTH_DB=admin

uv run pytest tests/integration/test_schema.py -q
uv run pytest tests/integration -v
```

The suite reads `MONGO_HOST`, `MONGO_PORT`, and optional credentials via
`AuthCredentials.from_environ()`. It does not consume `MONGODB_URI`; the new
read-preference example does, separately.

Choose a deployment supporting the features under test. Transactions need a
replica set or appropriate sharded cluster; the MongoDB `bulkWrite` command
needs MongoDB 8.0+. Advertised replica-set member addresses must resolve from
the test process. A reachable seed with unreachable advertised members can
still fail server selection. Do not change routing expectations just to make
a standalone deployment pass replica-set-only scenarios.

## Linting, typing, syntax

```bash
uv run ruff check kover tests examples
uv run pyright kover tests examples
uv run python -m compileall -q kover tests examples
git diff --check
```

Ruff selects all rules with project-specific exceptions. Follow existing
Google-style docstrings, double quotes, and the 79-character Python line limit.
Pyright uses strict checking. Check the files you touch first, then broader
groups; distinguish pre-existing failures from regressions.

Use `ruff format --check` on changed Python files when checking formatting;
review changes before running a formatter across the entire repository.

## Adding a regression test

1. Reproduce the failure with a focused test and inspect the full traceback.
2. Choose the narrowest boundary: pure policy, injected executor/discovery,
   local wire server, or a real MongoDB integration test.
3. Use `AsyncMock` for awaited operations and `autospec`/protocol specs where
   practical. Assert meaningful arguments, including timeouts passed through
   composition, not obsolete call signatures.
4. For concurrency tests, synchronize with events instead of arbitrary sleeps.
   Clear reused events between phases; otherwise a wait can succeed before the
   new task actually enters its factory. Bound waits and cancel/await pending
   tasks in cleanup so a failure cannot hang the suite.
5. Check cancellation **and** ordinary exception paths release reserved pool
   capacity. Cleanup must not replace the failure being investigated.
6. Run the new test and neighboring tests, then lint/type-check changed files.

Do not add `input()`, interactive debuggers, or live-database dependencies to
unit tests. Avoid broad refactors while fixing a lifecycle regression. Tests
should verify the correct contract, not make production code emit the wrong
exception merely to satisfy a race-dependent assertion.

## Running examples

Run examples as modules from the repository root:

```bash
uv run python -m examples.read_preferences
```

The read-preference example only reads data and accepts host/port/auth variables
or `MONGODB_URI`. Use a replica set with secondaries to observe all modes.
Its explicit configuration uses a three-second selection timeout; with a URI,
set `serverSelectionTimeoutMS=3000` to keep unavailable-secondary demonstrations
short. Other examples may write or delete data: inspect them before running.

## Documentation changes

Keep this directory, the [README](../README.md), and runnable examples aligned
with the actual API. Document limitations as well as features: no background
monitoring, no automatic command/transaction retries, fixed-server direct
connections, and currently unapplied transaction options.

Validate Python snippets for syntax, check relative Markdown links, and execute
examples against a disposable deployment when available. Do not claim real
secondary/failover coverage from a standalone run or from mocks alone.