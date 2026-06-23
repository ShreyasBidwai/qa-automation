# ADR-0047: Structured internal incident capture (Dev Suite, slice 1)

- Status: Accepted
- Date: 2026-06-23
- Deciders: Engineering

## Context

When Polaris itself fails during its work — a run errors, ingest fails, a provider
call dies, the orchestrator/a job throws — the only record today is raw logs. An
operator can't diagnose a failed AAHOA run without grepping them. This slice
captures those failures as structured **incidents**. Capture ONLY: not the UI, not
aggregation, not alerting, not auto-anything.

## Decision

### The `incidents` table (migration 0026, linear)

A standalone operator diagnostic log: `timestamp` (created_at), `phase`,
`component`, nullable `project_id` + `run_id`, `exception_type`, `message`,
`traceback`, and a `fingerprint`. **Not project-scoped** and intentionally **no
foreign keys** on `project_id`/`run_id` — an incident is the record of *why*
something failed and must outlive the entities it references (a deleted project must
not erase it). `phase` is a validated string (no new enum).

### Fingerprint — the root-cause-key idea, pointed inward

`fingerprint = sha256(exception_type + "\n" + normalized_location)[:16]`, where the
location is the deepest traceback frame's `file:function` with the build prefix
stripped and **without the line number** (which shifts on edits). So the SAME
failure groups across occurrences and across code changes — the same idea ADR-0021
uses for findings, applied to Polaris's own failures. Deterministic.

### Capture at the real seams — side-effect-safe

`IncidentRecorder.record` writes an incident in a **fresh session** (independent of
the failed one, which is typically aborting, so the record survives the work's
rollback). It is **best-effort**: it NEVER raises and NEVER swallows the underlying
exception — the caller records, then re-raises / handles exactly as before; a
recording failure is logged, not fatal. Two seams:

- **The job worker** is the universal seam: every piece of Polaris's autonomous work
  (ingest, generation, execution, the orchestrator) runs as a durable job, so the
  worker's failure boundary captures all of it, with `phase` derived from the job
  kind (`RUN → execution`, `INGEST → ingest`) and the project from the claimed job.
- **Provider calls** are synchronous, so instead of recording at that depth they
  **tag** the exception (`_polaris_incident_phase = "provider"`) as it propagates;
  the worker reads the tag and attributes the incident precisely (no DB session
  needed at the inner seam). Tagging is pure metadata — it never alters control flow.

Phases `generation` / `orchestrator` are reserved for finer inward tags at those
seams later; today they surface under `execution` with a full traceback that
identifies them. Existing fail/retry behaviour is byte-unchanged (the recorder runs
*before* the unchanged finalize path, and can't fail it).

### Operator-only read API

`GET /incidents` (newest-first, filter by `phase`/`project_id`) and
`GET /incidents/{id}` (with traceback), gated by the instance operator flag
(`OperatorUser` → 403 for a non-operator), cross-tenant like the ops view. No
mutation API. This is the seam the operator UI will consume later.

## Consequences

- A failed run is diagnosable from structured records, not raw logs; the fingerprint
  makes recurring failures visible as a group later.
- **Scope / honesty guardrail:** this captures and surfaces failures for humans. It
  does NOT aggregate, alert, or modify Polaris — and Polaris NEVER auto-modifies
  itself in response to an incident. Capture is observation, not action.
- Best-effort + fresh-session recording means capture can never break a run; the
  cost is that a captured incident is itself lost if its own write fails (logged).
