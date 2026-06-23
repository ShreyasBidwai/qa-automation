# ADR-0048: Run/finding payload enrichment — friendly run number, timestamps, severity breakdown

- Status: Accepted
- Date: 2026-06-23
- Deciders: Engineering

## Context

The dashboard, runs, and projects screens want fields the run/finding payloads don't
carry, so they show "—" or a short-form UUID for run ids. Three additive additions
close the gap — exposing real data plus one small counter. (Out of scope: richer
triage states / "snooze" — a separate feature.)

## Decision

### Friendly run number — per-project, monotonic, concurrency-safe

A run gets a friendly `#N` per project, assigned at creation and stable thereafter.

- `runs.run_number` (nullable, additive) with a unique `(project_id, run_number)`
  index. `projects.run_counter` (the monotonic source).
- **Assignment** (`RunRepository.next_run_number`): a single
  `UPDATE projects SET run_counter = run_counter + 1 ... RETURNING run_counter`. The
  atomic increment takes a row lock on the project, so two concurrent run creations
  always receive **distinct** numbers; the unique index is the backstop. The
  increment runs **inside the run's transaction**, so a run that rolls back frees its
  number — failures leave no gap.
- **Concurrency note:** because the increment is part of the (long) run transaction,
  the project row lock is held until the run commits — concurrent *same-project* run
  creations serialize on it. That is correct (no duplicates) and rare (runs are
  usually one-at-a-time per project); a separate short-lived increment transaction is
  the optimization if concurrent same-project runs become common.
- **Backfill** (migration 0027): existing runs are numbered `1..N` per project by
  `ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY created_at, id)` —
  deterministic — and each project's counter is set to its run count, so the next run
  continues the sequence.

Exposed on `RunListItem` and the run status payload (null until the run row exists —
a queued job or a mode-c authoring run has none).

### Timestamps / age

`created_at` + `finished_at` are surfaced on `RunListItem` and the run status payload,
and `created_at` on the finding payload (the "when"/age the screens render). The data
already exists; the backend sends ISO timestamps and relative-time formatting stays in
the frontend.

### Per-run severity breakdown — batched, reused

`RunListItem.severity_breakdown` carries open-findings counts by `critical`/`major`/
`minor`. It REUSES the inbox's "currently open" definition
(`OpenFindingsReader.severity_counts_by_run` → `_open_findings_for_runs`: muted +
heal-superseded excluded) and the existing severity vocabulary, so the per-run
breakdown can't drift from the inbox. It is **batched** — a fixed number of grouped
queries per page of runs regardless of run count (no N+1, same pattern as the
projects-list enrichment). A run with no open findings shows zeros.

## Consequences

- Additive only: every new field has a default, so existing run/finding consumers are
  unchanged.
- The run number is stable, per-project, and never duplicated; the severity counts and
  the open-findings inbox agree by construction.
- No re-derivation: pass-rate, the open-findings definition, and severity are reused,
  not reimplemented.
