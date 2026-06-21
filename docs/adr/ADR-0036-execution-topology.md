# ADR-0036: Runs are dispatched to decoupled runner workers over the durable queue

- Status: Accepted
- Date: 2026-06-22
- Deciders: Engineering

## Context

Through B4, a real run executed **in-process on the backend**: the `RunExecutor`
shells out to the Pest/Playwright toolchains as subprocesses of the API process
(`app.execution`). That requires every stack's toolchain — PHP/Composer/Pest,
Node/Playwright + browsers — on the **backend's PATH**. Fine on one dev box;
wrong for a deployable product. The packaged backend image deliberately ships
none of them, so `EXECUTOR_MODE=orchestrator` simply raised
("requires toolchains, not wired into the packaged image").

B4 already gave us the missing primitive: a **durable Postgres job queue** with
`FOR UPDATE SKIP LOCKED` claiming, cancellation, and retry (ADR-0034), plus a
worker loop (`JobWorker`). A run is already a `JobKind.RUN` row. The remaining
shift is *topological*: move execution off the control plane and onto separate,
toolchain-present workers that claim from the same queue.

## Decision

**Split the control plane from the execution plane along the existing queue seam.**

- **The backend (control plane) is toolchain-free and enqueue-only in the
  decoupled deployment.** It authorizes + enqueues run/ingest jobs (durable rows)
  and reports status/findings by reading the DB. It composes **no executor**.
- **Runner workers (execution plane) carry the toolchains.** A worker process
  (`python -m app.worker`) runs the B4 `JobWorker` poller, claims due jobs
  (`SKIP LOCKED`), executes them against the target via the real executors, writes
  `results`/`findings` back **through the DB**, and marks the job terminal. B4's
  claim / cancel / retry semantics are reused unchanged.
- **The runner images are promoted to request-time workers.** The Pest and
  Playwright images already bundle the backend code + their toolchain (they ran the
  heavy test lanes); the same images now run the worker loop as their command. No
  new toolchain image is invented — the test-lane images *become* the worker
  images.

### The dispatch protocol

1. Backend: `POST /runs` (or `/ingest`) → authorize → **enqueue** a durable job
   (`status=queued`, the run request serialized into `payload`) → `202`. The row is
   committed before the response so a worker can see it immediately.
2. A runner worker claims the row (`queued → running`, `SKIP LOCKED`), runs the
   composed executor in **its own** session/environment, and on success writes the
   run + results + findings and `mark_succeeded` (compare-and-set vs `running`, so a
   concurrent cancel is never clobbered); on error it retries-with-backoff or fails.
3. The client polls `GET /jobs/{id}` / `GET /runs/{id}/findings` — the **unchanged**
   poll contract. Tenancy is unchanged: the worker writes under the job's
   `project_id`; reads stay org-scoped (ADR-0033).

### `EXECUTOR_MODE`, restated

- `stub` (default, single box): the backend composes the `StubRunExecutor` and
  dispatches **in-process** (the B4 BackgroundTask hint) — clone→up still works with
  zero toolchains.
- `orchestrator` (decoupled, real deployment): the backend composes **no** executor
  / ingestor (enqueue-only); it boots fine and enqueues. Execution is done by runner
  workers. This is what previously raised — now it is a real, bootable topology.

The endpoints reflect this: they **always enqueue**, and only fire the in-process
dispatch hint when this node actually carries an executor. A backend with no
executor is no longer a `503` — it is the slim control plane, by design.

### Why not a synchronous executor service / direct RPC

We already run the durable queue; routing runs through it gives durability,
concurrency (`SKIP LOCKED`), cancellation, retry, and back-pressure for free, and
keeps the backend ignorant of *where/how* execution happens. A bespoke RPC/executor
service would re-implement all of that and add a second moving part. The queue is
the seam; workers are just another consumer of it.

## Consequences

- The backend image stays slim and toolchain-free and still fully functions
  (enqueue + report); runner workers scale independently and per-stack.
- Real execution becomes turnkey: the worker image already carries Pest +
  Playwright + browsers (asserted by the heavy lanes), so wiring the production
  AI-backed orchestrator executor later is a drop-in behind `build_run_executor`
  with **no topology or infra change**. Until then a worker runs the round-trip
  executor (`stub`), which still persists a real run + finding through the DB —
  the decoupled path is exercised end-to-end.
- Two planes to run in production (backend + ≥1 runner worker), added to compose as
  separate services. The backend's in-lifespan poller is disabled in the decoupled
  deployment (the dedicated workers drain the queue); it stays on only for the
  single-box `stub` mode.
- No schema change — runs were already a queued job kind (B4); B5 is wiring +
  packaging + topology, head stays `0020`.
