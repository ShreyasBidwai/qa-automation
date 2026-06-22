# ADR-0044: Wiring DB-state testing into the live run orchestrator

- Status: Accepted
- Date: 2026-06-22
- Deciders: Engineering

## Context

B10 (ADR-0043) delivered the DB-state engine — the non-prod safety gate, per-project
tier, table-state oracles, disposable-DB provisioning — but explicitly deferred
wiring it into a real run, so it emitted no findings during an actual run. This
closes that: a run on a project with DB-state enabled produces DB-state findings
that land in the same findings pipeline as everything else.

## Decision

### A DB-state phase at the orchestrator seam

`DbStateRunPhase` runs after a run executes (Mode B), between finding assembly and
scoring, as an **optional injected collaborator** of `ModeBOrchestrator` (absent →
identical behaviour to before; this is how existing runs stay unchanged). It:

1. reads the project's `db_state_tier`;
2. derives checks deterministically from the Brain — each `endpoint --writes-->
   table` edge becomes a table-state assertion (a DELETE endpoint on a table with a
   `deleted_at` column asserts the soft-delete **rule** → rule-derived; otherwise it
   asserts the write landed a row → characterization);
3. runs them against the run's target database;
4. emits each failure as an ordinary `Finding` (`layer=db`), tagged with the honest
   oracle source and tied to the Brain table node (the location carries the table at
   the deepest end), anchored to one of the run's results for the FK/evidence join.

Because DB-state findings are plain `Finding` rows, they flow through the existing
score → classify → rank → list pipeline and render in the dashboard at the table-end
node — no consumed contract changed, no new persisted schema, no migration.
`root_cause_key` is `db_state:<table>:<predicate>#<oracle>` — deterministic, so
re-runs re-key stably and cross-run history works.

### The safety rule still governs — enforced at the seam

The B10 rule is unchanged: every DB-state **write** path goes through
`DbStateExecutor.ensure_writable` → the prod-refusal gate. `full` is the
write-capable tier, so the phase runs the gate **before it connects**; `read_only`
opens a `READ ONLY` connection and never writes; `off` (default) returns before
touching anything. If the target fails the gate, the phase **refuses** the DB-state
portion and returns a report saying why — it never raises. The orchestrator wraps
the whole phase in a defensive guard as well, so DB-state can never crash the rest of
a run no matter what. This is tested at the orchestrator seam (a prod-target run
completes normally and produces its non-DB findings while the DB-state portion is
refused), not only at the unit.

### Heavy lane, like the rest of the execution edge

The real connector (`EngineTargetConnector`) and disposable-DB provisioning are the
execution edge, exercised in the `db_state` heavy lane (`make test-db-state`). The
tier-gating, the gate-at-the-seam, and the finding shape/tagging/blast-path are
hermetic and in the fast suite — the safety-critical behaviour is never behind an
optional lane.

## Consequences

- DB-state findings are first-class findings: same table, same dashboard, same
  history — distinguished only by `layer=db` and their oracle tag.
- `off` projects (every existing project) get exactly zero behaviour change.
- The non-prod guarantee now holds end-to-end through a live run, and is pinned by a
  seam test, not just the B10 unit test.
- Deriving richer checks (specific row selectors, column expectations from documented
  contracts) builds on this seam additively.
