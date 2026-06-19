# ADR-0023: Cross-run history classification — new vs regression vs flaky vs known

- Status: Accepted
- Date: 2026-06-19
- Deciders: Engineering

## Context

A finding is more actionable when the report says whether it is **new**, an
ongoing **known** issue, a **regression** (a bug that had cleared and came back),
or **flaky** (a result that flips run to run). T7.4 fills the `status` placeholder
by classifying each finding against the project's recent run history, joined on
the stable `root_cause_key` from ADR-0021.

"What counts as a regression vs a flake" is a real product decision: a bug that
cleared once and returned is a regression worth alarming on; a result that
oscillates is noise to quarantine, not a fix to celebrate. The rule must be
**deterministic**, **project-scoped**, and computed over a **bounded** window so a
project with thousands of runs stays cheap.

## Decision

**Status vocabulary** (`FindingStatus` enum, stored as its string in the existing
`findings.status` column): `new | known | regression | flaky`. `open` remains the
pre-classification default.

**The window.** The `N` runs immediately prior to the current run (default
`N = 10`, configurable), taken from the **`runs`** table ordered by
`(created_at, id)` and bounded to `N`. Runs older than the window are ignored.

**Presence.** For a finding with key `K`, a window run "has `K`" iff a `findings`
row exists for `(that run_id, K)`. Absence of `K` in a run is treated as "not
failing that run" — including all-pass runs (which produce no findings at all).
This yields a boolean **presence vector** over the window, oldest → newest.

**Classification** (let `flips` = transitions between consecutive entries in the
presence vector; `seen` = any present; `last` = present in the immediately-prior
run):

- **flaky** — `flips >= 2`: `K` oscillated across the window.
- **regression** — `seen and not last`: `K` appeared earlier, had cleared by the
  immediately-prior run, and is back now.
- **known** — `last`: `K` was present in the immediately-prior run (ongoing).
- **new** — otherwise: `K` never appeared in the window.

**Precedence: `flaky > regression > known > new`** (the order above; the first
matching rule wins). A single clear-and-return is exactly one flip → regression;
two or more flips is flaky, so flaky deliberately wins over regression when a key
both returned *and* oscillated. Counting flips over the prior window only (not the
always-present current run) is what keeps a plain regression (`…T,F` → 1 flip)
distinct from real oscillation.

**No new table.** History is sourced from the existing `findings` rows
(`run_id + root_cause_key` for presence) and the `runs` table (for the window and
its order). A `finding_occurrence` table was considered and rejected: the window
query is a bounded `runs` enumeration plus one indexed `findings` lookup
(`project_id, run_id, root_cause_key`) — it needs no denormalized occurrence log,
so adding one would be dead weight. No migration.

## Consequences

**Easier**
- The report distinguishes a returning bug (regression — alarm) from a noisy one
  (flaky — quarantine) from steady state (known) and first sightings (new),
  deterministically and from data already stored.
- No schema change: `findings.status` (ADR-0020) holds the classification; the
  join key is the `root_cause_key` from ADR-0021.

**Harder / watch-outs**
- Run order relies on `created_at` (tie-broken by `id`). Production runs are
  created in separate transactions so timestamps are distinct; fixtures must set
  explicit timestamps (within one transaction `now()` is constant).
- The window is bounded to `N`: a bug that recurs on a cycle longer than `N` runs
  reads as `new` each time. `N` is tunable here by ADR, not scattered constants.
- `flips >= 2` is a coarse flake threshold; a bug that genuinely regressed twice
  within the window is reported flaky. Acceptable — repeated regression of the
  same key is itself a signal to quarantine.
