# ADR-0034: Durable job queue on Postgres (FOR UPDATE SKIP LOCKED), not Redis

- Status: Accepted
- Date: 2026-06-21
- Deciders: Engineering

## Context

B1 shipped jobs as an in-memory `JobRegistry` + FastAPI `BackgroundTasks`
(ADR-0026): a dict on `app.state` plus fire-and-forget tasks. It was the right
amount of machinery then, but it has two fatal properties for a reliability sprint:

- **Jobs vanish on restart.** The registry is per-process memory; a deploy or crash
  loses every in-flight and pending job, and the client polling `GET /jobs/{id}`
  gets a 404 for work that was really running.
- **No real lifecycle.** No persistence, no concurrency control across workers, no
  cancellation, no retry/backoff.

B4 needs a **durable** queue behind the *same* seam (the `RunExecutor`/`Ingestor`
ports and the `GET /jobs/{id}` poll contract) so the run flow keeps working while
the implementation changes underneath. The choice is **Arq/RQ + Redis** vs a
**DB-backed queue on the Postgres we already run**.

## Decision

**A DB-backed durable queue on Postgres, claimed with `SELECT … FOR UPDATE SKIP
LOCKED`.** A `jobs` table is the single source of truth for job lifecycle; an
in-process worker polls it; the API enqueues rows and dispatches them.

### Why not Redis

Redis + Arq/RQ has nicer native queue semantics, but it adds a **new piece of
infrastructure** to run, secure, back up, monitor, and wire into every environment
(dev compose, CI, prod). For our volume — a handful of long-running ingest/run jobs
per project — that operational surface buys very little. Postgres `FOR UPDATE SKIP
LOCKED` is the well-trodden "just use your database as a queue" pattern: each worker
atomically claims the next eligible row and skips rows other workers hold, giving
safe concurrency with **zero new infra**. We already depend on Postgres for
everything else, and durability/transactions come for free. Per the sprint's
guidance ("lean to whichever adds the least operational surface for the value"),
Postgres wins decisively. If throughput ever outgrows polling, swapping in Redis is
a contained change behind the same `JobQueue` interface.

### The model

`jobs` rows carry the full lifecycle (ADR-0026's poll contract is preserved):

- `status`: `queued → running → succeeded | failed | cancelled` (a native
  `job_status` enum). `kind` is `ingest | run`.
- `payload` (jsonb): everything needed to run the job **after a restart** (the
  serialized run request) — the work does not depend on in-memory request state.
- `attempts` / `max_attempts` + `available_at`: retry-with-backoff. A failure below
  the cap re-queues the row with `available_at = now + base · 2^(attempt-1)`; at the
  cap it goes to `failed`.
- `locked_at` / `locked_by`: the worker lease — used to surface **stuck** jobs
  (running longer than a threshold) to the operator view (ADR-0035).
- `run_id` / `summary` / `detail`: the orchestrator's result (or the failure type —
  never a secret).

### Claiming, concurrency, cancellation

- **Claim** is one statement: `SELECT … WHERE status='queued' AND available_at <=
  now() ORDER BY available_at, created_at FOR UPDATE SKIP LOCKED LIMIT 1`, then flip
  to `running`. `SKIP LOCKED` means N concurrent workers never claim the same row.
- **Cancellation** is cooperative and race-safe: cancelling a `queued` job flips it
  to `cancelled` so it is never claimed; cancelling a `running` job also flips it,
  and the worker's terminal write is a compare-and-set that refuses to overwrite a
  `cancelled` status — so a finished-but-cancelled job stays cancelled.

### Dispatch + recovery

The API still uses `BackgroundTasks` — but **only** as a low-latency, in-process
*dispatch hint* that processes the just-enqueued row immediately (this keeps the
synchronous run flow the existing tests rely on). The durable row is the source of
truth; a **worker poller** (started in the app lifespan, gated by
`job_worker_enabled`) claims any row the dispatch hint didn't run — orphans after a
restart, and retries whose backoff has elapsed. So "survives restart" holds: a
fresh process's poller picks up `queued` rows it never saw enqueued.

## Consequences

- No new infrastructure; jobs persist across restarts; concurrency, cancellation,
  and retry/backoff are real and tested directly against `JobQueue`/`JobWorker`.
- The `GET /jobs/{id}` and run/findings poll contracts are unchanged; the run flow
  keeps working through the new queue.
- Polling has a small latency floor (the poll interval) for recovery/retry paths;
  the dispatch hint keeps the common path immediate. Acceptable at our volume.
- A migration adds the `jobs` table (0020, linear off 0019). The worker runs
  in-process for now; extracting it to its own process (or Redis) is a later,
  contained change behind `JobQueue`.
