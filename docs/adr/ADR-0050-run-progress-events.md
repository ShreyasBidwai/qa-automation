# ADR-0050: Structured run-progress events for a live run view

- Status: Accepted
- Date: 2026-06-24
- Deciders: Engineering

## Context

The frontend will show a live "watch the run happen" view — the journey as it
executes (select → generate → execute step-by-step → review). The backend must EMIT
that progress. This is plumbing built against the current run path so it is ready
when real runs (AAHOA) execute; if it needs adjustment under a real run, that's
expected. Scope here is capture + exposure (no UI).

## Decision

### Event model — `run_events`

An ordered, append-only log. One row per event:
`{run_id, project_id, seq, phase, step, status, detail, created_at(=timestamp)}`.

- **`run_id`** is the durable run handle the API already exposes — the **RUN job id**
  (every `/runs/{run_id}` route resolves that id). Keying on it means events exist for
  the WHOLE lifecycle, including generation that happens *before* the internal `runs`
  row is created, and the client streams the same id it got from `POST /runs`.
- **`seq`** is a per-run monotonic counter assigned in memory BEFORE the write, so
  ordering is deterministic regardless of commit timing; the unique `(run_id, seq)`
  index enforces it and dedups.
- **`phase`** ∈ {run, select, generate, execute, review}; **`status`** ∈ {started,
  passed, failed, skipped}; both validated strings (no pg enum). `run` frames the run
  as a whole — its terminal `passed`/`failed` event ends a live stream.
- **`detail`** is optional JSONB (which endpoint/page/test, counts, …).

Like `incidents` / `ai_usage`, it is an observability log with NO foreign key — it
records what happened and outlives the entities it references; never mutated.
Migration `0029_run_events`, linear off `0028_ai_usage`.

### Emit seam — best-effort, side-effect-safe, fresh-session

`RunProgressEmitter` mirrors `IncidentRecorder`: each event is written in a **fresh
session that commits independently**, so (a) a live streaming reader on another
connection sees events as the run produces them, and (b) the history survives even if
the run's own transaction rolls back. It **NEVER raises** — a failed emit is logged,
not fatal — so emission can neither break nor stall a run (the same rule as incident
capture). The emitter is installed for the duration of a RUN job via a context
variable (in the universal job-worker seam), so the synchronous-looking
orchestrator/lifecycle code emits through `emit(...)` without threading an emitter
through every call; any path with no emitter installed is a silent no-op.

Seams wired now: the job worker (install + a terminal `run/failed` fallback on a job
exception, so a stream always closes), `ModeBOrchestrator` (run start, select,
per-target generate, review, terminal run finish), `RunLifecycle` (execute phase +
one step per test result), and the demo `StubRunExecutor` (a believable canned
sequence so the live view can be built/demoed before real execution).

### Exposure — SSE stream + replay

- `GET /runs/{run_id}/events/stream` — **Server-Sent Events**. Chosen over WebSockets:
  one-way server→client progress over plain HTTP, no extra infra, native browser
  `EventSource`, and it rides the existing auth. The stream polls the committed
  `run_events` on a seq cursor and closes on the terminal run event, or when the job
  is terminal and drained, or at a safety cap — so it can never hang.
- `GET /runs/{run_id}/events` — plain replay/poll (optional `after_seq` cursor) for a
  finished or in-progress run.

Both are authorized reads (VIEW) and additive — no existing payload shape changes.

## Consequences

- The run path now narrates itself; the frontend can render the journey live (SSE) or
  reconstruct it after the fact (replay), ordered deterministically by `seq`.
- Emission is invisible to the run: a parse/DB failure is swallowed + logged; the run
  proceeds and commits exactly as before. Worst case the live view misses an event.
- Per-test granularity is emitted as each result is processed; the current runner runs
  a batch, so finer mid-test streaming awaits a streaming runner (future) — the seam
  is in place.
- Each event is its own short transaction (the price of live visibility); fire-and-
  forget emission is a future optimization if it ever matters.
