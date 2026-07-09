# ADR-0062 — Run preferences, one-click re-run, and run-scoped tests

## Status

Accepted.

## Context

A project accrues *n* runs, each started with a different combination of preferences
(mode, strategy, module scope, layers). Recent-runs lists showed only an opaque id +
pass rate, so an operator couldn't tell one run from another — let alone say "run that
same thing again". Two gaps followed:

1. **You couldn't recognise a run by what it tested.** Continuing "the Orders API run"
   meant reconstructing its preferences by hand in the run form.
2. **The generated-tests page always showed *every* test the project ever produced.**
   After a module-scoped run you had to hunt for the handful of cases that run actually
   authored, mixed in with everything else.

Both are answerable from data we already store — no new tables.

## Decision

**A run's preferences are read back from its job payload; run == job (ADR-0036).** A
Mode B/C run is created with its `id` pinned to the durable `job.id`, and the run
request is serialised into `job.payload` at enqueue. So the preferences are already
persisted — we just surface them:

- `JobQueue.get_many(ids)` batch-loads the jobs backing a page of runs (one query, no
  N+1), and `RunListItem.preferences` is projected from each payload by a pure
  `_run_preferences()` helper. The helper exposes only the *structured knobs* (mode,
  strategy, layers, modules, changeset size, describe-it layer) — **never the raw
  prompt text**, which can contain free-form user content and stays server-side.
- The frontend renders a short, deterministic label (`runPreferencesLabel`) —
  "Autonomous · modules: orders · API", "Autonomous · changed files (4) · UI",
  "Describe it · API contract" — so runs are distinguishable at a glance.

**Re-run copies the payload; it does not re-derive it.** `POST /runs/{id}/rerun`
(RUN-gated, project-scoped) enqueues a fresh job with `payload = dict(job.payload)` of
the source run and dispatches it. Because the payload IS the preferences, the new run
is a faithful continuation with zero reconfiguration — the exact "if the same
preferences are selected, just continue the previous one" the operator wanted.

**Tests can be scoped to a single run.** `GET /projects/{id}/tests?run={runId}` returns
only the cases that run exercised: the run's `Result` rows → their `test_case_id`s →
the project-scoped cases (still ordered newest-first, still paginated). A run's
Generate phase and status view link straight to this scoped view ("View this run's
tests"); the project header keeps a "View all tests" button (and the scoped page a
"View all tests" escape hatch) for the full list.

### Security

- **The prompt is never exposed.** `_run_preferences()` projects a fixed allow-list of
  structured fields; the free-text `prompt` is deliberately omitted from the API
  payload, matching the "never echo user content you don't need to" posture.
- **Re-run can't cross tenants.** It resolves the source run through the same
  project-scoped, RBAC-gated path as every other run action (RUN permission), then
  copies *that* project's payload — an outsider gets a 404, never another org's run.
- **Run-scoping can't leak.** The `?run=` filter reads `Result` rows already scoped by
  `project_id`; a run id from another project simply matches nothing (no cross-project
  read), exactly like the module filter in ADR-0061.
- The run id is only ever a uuid string-compared / used as a scoped filter key — never
  fed into SQL, a path, or a URL host.

## Consequences

- Recent-runs lists (project overview + the Runs page) now read as a legible history:
  each row shows what it tested and offers a one-click **Re-run**.
- "Continue this run" is a copy, not a reconstruction — it stays correct even as the
  run form's UI evolves, because it never goes through the form.
- The generated-tests page answers both "what did *this run* write?" and "what has the
  project produced overall?" from the same endpoint via one optional query param.
- Preferences are only as rich as the payload. A run enqueued before a new preference
  knob existed simply won't report that knob (the label degrades gracefully to what is
  present) — acceptable, since old runs predate the knob anyway.
- Shipped alongside: **Gitea** and **PM tool** get their own sidebar tabs (roadmap
  connector pages, "coming soon", static/no-backend) — the sidebar counterpart to the
  Project view's Connectors card (ADR-0061).
