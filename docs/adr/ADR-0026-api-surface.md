# ADR-0026: HTTP API surface + in-process background execution

- Status: Accepted
- Date: 2026-06-19
- Deciders: Engineering

## Context

The pipeline is now complete (ingest → Brain → generate → run → findings) but only
drivable from Python. The UI and real-app validation both need one cohesive HTTP
surface to drive a project end to end (TRD §4: REST, `/api/v1`, project-scoped).
This task is the **entry layer only** — it must *wire to* the existing
orchestrators (`ModeBOrchestrator`, the Mode C orchestrator, ingestion, the
finding pipeline), never reimplement them, and add **no new infra** (no broker, no
extra Docker) per the standing convention.

Two design questions: how to run long work (ingest/run) without blocking the
request, and how to keep the orchestrators swappable so the surface is testable in
the fast lane with no real generation/browser/Docker.

## Decision

**Thin routers over injectable ports.** Routes do validation + tenancy + job
bookkeeping only; the real work is behind two ports on `app.state`:

- `RunExecutor.execute(session, project_id, request) -> RunExecution` — the
  reference `OrchestratorRunExecutor` dispatches `mode_b` → `ModeBOrchestrator.run`
  (building the selection strategy via `build_selection_strategy`) and `mode_c` →
  the Mode C orchestrator. It *reuses* them; it adds no orchestration logic.
- `Ingestor.ingest(session, project_id) -> dict` — wraps the existing ingestion.

Composition sets the production ports; tests set stubs. The port contracts are
shaped to the orchestrators' real signatures (mypy-checked), so "wiring" is a
type-level guarantee, not a copy.

**In-process background execution (no new infra).** Long ops return immediately
with an id and are polled — but instead of a broker we use an in-memory
`JobRegistry` on `app.state` plus FastAPI `BackgroundTasks`:

- `POST /projects/{id}/ingest` → creates an `ingest` job, schedules the work,
  returns `{job_id, status}`; polled at `GET /jobs/{job_id}`.
- `POST /projects/{id}/runs` → creates a `run` job, returns `{run_id, status}`
  where `run_id` **is the job handle**; polled at `GET /runs/{id}` (status +
  summary) and `GET /runs/{id}/findings` (the ranked findings).

A background task opens its **own** session from the sessionmaker (the request
session is gone by the time it runs), executes the port, and records status +
the underlying DB `run_id` + a summary on the job. The handle is the public run
id; the orchestrator's `runs` row id is internal and reached via the job — the
orchestrators own run creation, so the API cannot know the row id before execution
and does not pretend to.

**Typed + scoped + honest errors.** Pydantic request/response schemas; the run
body is a discriminated union on `mode` (bad mode → 422). `change_impact` without
a changeset is a schema-level validation error (422). Unknown project / unknown
run → 404. Everything routes through the existing RFC-9457 problem+json handler.
Every read/write is project-scoped; one project's runs/findings are reached only
through that project's ids.

## Consequences

**Easier**
- The whole pipeline is drivable over HTTP for the UI and real-app validation,
  with the orchestrators reused verbatim and swappable for fast-lane tests.
- No new infra: background work is in-process; the `JobRegistry` is a dict. The
  `jobs` *table* (TRD §9) and a real broker are a later upgrade behind the same
  port + poll contract.

**Harder / watch-outs**
- In-process jobs do not survive a restart and do not scale across processes —
  acceptable for single-deployment dogfooding; the port/poll shape is broker-ready.
- The public `run_id` is the job handle, not the DB `runs.id`; findings are joined
  via the job's recorded run id. A run requested in `mode_c` (authoring) produces
  no run/findings, so its findings list is empty by design.
- The reference `OrchestratorRunExecutor` needs heavy collaborators (runner,
  resolver, generator, AI) supplied at composition; the API boots without them and
  returns a typed 503 until configured, so the no-infra fast lane stays green.
