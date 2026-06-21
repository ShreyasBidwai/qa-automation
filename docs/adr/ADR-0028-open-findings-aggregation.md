# ADR-0028: "Currently open" findings aggregation

- Status: Accepted
- Date: 2026-06-21
- Deciders: Engineering

## Context

The redesigned UI adds a **Findings inbox** ("what is broken right now") and
open-finding counts on the projects list / project overview. The run dashboard
answers *"what did this run find"*; the inbox answers the different question
*"what is currently broken across my projects"*. We need one precise, deterministic
definition of "currently open" so the inbox, the per-project view, and the counts
all agree.

The inputs already exist: per-run `findings` (ADR-0020/0021), cross-run history
(ADR-0023), and triage dispositions keyed by `root_cause_key` (ADR-0027).

## Decision

**"Currently open" = the open findings of each project's _latest run_.** Precisely,
for `GET /findings` (global) and `GET /projects/{id}/findings`:

1. **Latest run per project.** Take the single most-recent `runs` row per project
   (`DISTINCT ON (project_id) … ORDER BY created_at DESC, id DESC`). Older runs are
   not consulted — the latest run is the current state of the world.
2. **Its findings.** All `findings` rows for those latest run(s). Each is one row
   per `(run_id, root_cause_key)` (unique index), so within a project's latest run
   the set is **already deduped by `root_cause_key`** — no cross-run union, no dups.
3. **Join triage, exclude muted/resolved.** Left-join `finding_triage` on
   `(project_id, root_cause_key)` (ADR-0027) and **exclude**
   `resolved | wont_fix | false_positive`. Absent record or `open` / `acknowledged`
   counts as open (acknowledged = being worked, still broken).
4. **Rank by severity.** Sort `severity desc, confidence desc, root_cause_key`
   (the same `rank_findings` order the run dashboard uses).
5. **Paginate** (`limit`/`offset`) with a stable `total`. The page is returned in
   the **same `FindingResponse` shape** (location + evidence + history + triage) as
   the run dashboard, so the UI renders inbox rows and the drawer identically.

Soft-deleted projects (ADR-0029) are excluded.

**Consequences of the definition (intentional):**
- A finding the latest run did **not** reproduce does not appear — it is no longer
  current, even if an older run had it.
- A `root_cause_key` triaged `wont_fix` / `false_positive` / `resolved` never
  appears — muting follows the issue across runs (ADR-0027), so it stays muted.

## Batching (no N+1)

The selection is the gated query and is batched to a fixed number of statements
regardless of finding count: one `DISTINCT ON` for the latest runs, one
`findings WHERE run_id IN (…)`, one `finding_triage WHERE (project_id,
root_cause_key) IN (…)`, one count. Detail (evidence/history) reuses the existing
batched `FindingDetailReader` **per `(project, latest_run)` group on the page** —
constant queries per group, bounded by the page size (a single project's inbox is
exactly one group → fully batched). No per-finding query on any path.

## Alternatives rejected

- **Union of all open findings across all runs.** Re-surfaces bugs the latest run
  already fixed; "open" would lag reality. Latest-run is the honest "now".
- **Status column on `findings`.** `findings.status` is the *derived history*
  classification (ADR-0023), not a disposition; overloading it would conflate the
  two axes. Triage (ADR-0027) is the disposition source of truth.

## Known edge (parked, per the sprint plan)

If a project's latest run was **change-impact-scoped**, it covers only the changed
slice, so the inbox reflects that slice — acceptable for v1.
