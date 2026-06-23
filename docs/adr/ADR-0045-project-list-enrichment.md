# ADR-0045: Enriched projects-list payload (batched, read-time)

- Status: Accepted
- Date: 2026-06-23
- Deciders: Engineering

## Context

The projects list could only show name / repo / registered-at, because
`ProjectListItem` carried nothing about a project's health. The projects-list
re-skin needs, per project: its stack, a last-run summary (pass-rate + finished-at +
run status), an open-findings count, and an overall status. These are read-time
aggregates over existing data — no new schema.

## Decision

### Additive fields, computed BATCHED (no N+1)

`ProjectListItem` gains `stack`, `status`, `open_findings_count`, and `last_run`
(a `LastRunSummary`). All have defaults, so existing list consumers are unaffected
(additive contract). For a page of N projects the enrichment costs a **fixed**
number of grouped queries, never one-per-project:

- **latest run per project** — one `DISTINCT ON (project_id)` query
  (`RunRepository.latest_run_per_project`), same ordering as the findings inbox;
- **pass-rate** — one grouped outcome-count query for those runs
  (`ResultRepository.outcome_counts_by_run`, the cross-project sibling of the
  per-run version the runs list already uses), fed through the **shared** `pass_rate`
  function (moved to `reporting.project_summary`, now used by both the runs list and
  the projects list — pass-rate is defined once);
- **open-findings count per project** — `OpenFindingsReader.open_counts_by_project`,
  which reuses the inbox's exact "currently open" definition (latest run, deduped by
  `root_cause_key`, excluding resolved/wont_fix/false_positive **and** heal-superseded
  drift) via a shared `_open_findings_for_runs` helper, grouped by project. The
  projects-list count therefore can never drift from the findings inbox.

A `ProjectSummaryReader.summaries_for(project_ids)` orchestrates these three reads
and is what the endpoint calls. `project_ids` are the caller's already-authorized
page, so no extra RBAC lives here.

### Overall status — a deterministic derivation

`status` is derived, not stored, with a fixed precedence:

- `never_run` — the project has no runs;
- `errored` — the latest run errored (an infra/runner failure, not a test outcome);
- `action_needed` — there are open findings;
- `passing` — a completed latest run with no open findings.

A project with no runs degrades cleanly: `last_run = null`, `pass_rate = null`,
`open_findings_count = 0`, `status = never_run`.

## Consequences

- The projects list can be re-skinned with real health signals; the numbers match
  the runs list (pass-rate) and the findings inbox (open count) by construction,
  because both definitions are reused, not re-derived.
- No migration — purely read-time aggregates. The cost is bounded and tested
  (a query-count test proves the per-page query count is constant across N projects).
