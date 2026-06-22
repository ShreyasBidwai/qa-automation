# ADR-0042: Per-test transactional isolation

- Status: Accepted
- Date: 2026-06-22
- Deciders: Engineering

## Context

The backend suite runs single-process against one shared test database. Until now
each fixture managed its own connection, and the `app_client` fixture let the app
**commit** through its own sessionmaker with no rollback. So any test that committed
rows (e.g. an open finding) left them in the database for later tests to read. The
global, unscoped read `open_findings(None)` would then see another test's rows, and
the assertion outcome depended on *which tests ran before it*. ADR-0041's sprint hit
this and worked around one instance (seeding only a heal-suppressed finding so the
committed rows couldn't appear in a default inbox). That treated a symptom; the leak
itself remained, and a QA product whose own gate (`make test`) can flip green/red by
test co-residency cannot be trusted by the workflows that depend on that gate.

## Decision

### One transaction per test, shared by the app and direct DB access

Every test runs inside a single outer transaction on a single connection, rolled
back at teardown. A `_isolation` fixture opens one connection, begins the outer
transaction, and builds a connection-bound `async_sessionmaker` with
`join_transaction_mode="create_savepoint"`. In that mode a session that `commit()`s
on a connection already inside a transaction **releases a SAVEPOINT** instead of
committing for real — so every commit the code under test makes lands inside the one
outer transaction, and rolling it back at teardown discards everything.

The critical part is **sharing**: `db_session` (direct DB access) and `app_client`
(what the API commits) both bind to *this* sessionmaker. `app_client` boots the real
app through its lifespan, then repoints `app.state.sessionmaker` at the shared one.
Every request-time DB read goes through `request.app.state.sessionmaker`
(deps/runs/projects/health, verified by grep), so the swap captures everything the
API commits into the per-test transaction. Without the share, the rollback wouldn't
cover what the API committed and the leak would persist.

Why the swap is safe and needs no production change:
- The job worker is disabled in tests (`job_worker_enabled=False`), so nothing
  captured the app's original sessionmaker before the swap.
- Dispatched jobs run as FastAPI **background tasks**, after the request's session
  has closed; the single shared connection is only ever touched serially (no
  concurrent use), so a connection-bound sessionmaker is sufficient.
- `app.state.engine` is used only at startup/shutdown, never at request time.

No application, behaviour, or contract code changed — only `tests/conftest.py`.

### Connection frugality (so a shuffled run can't exhaust the server)

A per-test engine is required because pytest-asyncio uses a function-scoped event
loop (a session-scoped async engine would be used across loops). To keep that from
accumulating connections toward the server cap during a heavy run, the per-test
engine uses `NullPool` (no idle connections), and tests set `DB_POOL_SIZE=1` /
`DB_POOL_MAX_OVERFLOW=0` so the per-test *app* engine (the production default is
10+5) stays tiny. These are test-env settings, not production changes.

### A durable guard: shuffle every run

`pytest-randomly` is added to the test requirements. It shuffles test order every
run and prints the seed, so order-dependence can't silently return — and a failure
is reproducible with `--randomly-seed=N`. The suite was verified green across the
default order and seven distinct seeds.

## Consequences

- Committed rows can never leak between tests; the suite is order-independent.
- ADR-0041's workaround was reverted: the reconciliation test again seeds the
  realistic mix (a real open finding *and* a heal-superseded one) — the clearest
  expression of what it checks — because isolation now rolls it back.
- A guard (`test_db_isolation.py`) pins the property: two tests each commit an open
  finding and assert the unscoped global reader sees only its own, and a third shows
  an API-committed row is visible to the direct `db_session` (proving the share).
- The gate now runs shuffled, so the cost of a future order-dependent test is paid
  immediately (a red gate with a reproducible seed), not later as a flaky mystery.
