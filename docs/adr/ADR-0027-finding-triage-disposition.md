# ADR-0027: Finding triage disposition is keyed by the logical issue

- Status: Accepted
- Date: 2026-06-20
- Deciders: Engineering

## Context

The finding-detail drawer needs real triage actions: a human marks an issue
acknowledged / resolved / won't-fix / false-positive so the tool stops surfacing
a known or rejected issue as if it were fresh.

There are already two finding "status-ish" concepts, and triage must not be
conflated with either:

- **`Finding.status`** (ADR-0023) — the *derived* cross-run history
  classification: `new | known | regression | flaky`, computed each run by the
  history classifier. It is machine-derived, recomputed every run, and per-run.
- **`results.triage`** (`Triage` enum: real-bug / bad-test / flaky / …) — a
  per-*result* cause label, a different axis entirely.

The key product question is **what a triage decision is attached to**. A finding
*row* is per-run (`findings` has one row per `(run_id, root_cause_key)`). If
triage were keyed to that row, every new run would create a fresh, untriaged row
and the human would have to re-triage the same issue every run — the exact
re-surfacing pain we are trying to kill. Triage is a statement about the
**logical issue**, not the run instance.

## Decision

**A new `finding_triage` table, keyed `(project_id, root_cause_key)`** — one
disposition per logical issue per project, unique on that pair. The
`root_cause_key` (ADR-0021) is the stable, deterministic identity of an issue
across runs, so a disposition set in one run is found by any later run whose
findings carry the same key.

**Distinct field, distinct vocabulary.** A new `TriageStatus` enum
(`triage_status` pg type): `open | acknowledged | resolved | wont_fix |
false_positive`. **Absent record = `open`** (the default; we don't write a row
until someone triages). `known` is deliberately *not* a triage value — it would
collide with the derived `history.classification`; muting a known issue is
expressed as `wont_fix` / `false_positive`.

**Upsert, not insert.** `PATCH /runs/{run_id}/findings/{finding_id}` resolves the
finding's `root_cause_key` and upserts the `(project_id, root_cause_key)` row
(Postgres `INSERT … ON CONFLICT … DO UPDATE`) — idempotent, race-free, no
duplicate dispositions. `note` is optional free text; `triaged_at` is stamped on
every write.

**Read path.** The triage block (`{ status, note?, triaged_at? }`) is merged into
the findings response, looked up by `root_cause_key` in **one batched query** for
the whole run (no N+1). Findings with no record report `open`.

**Attribution is deferred, honestly.** *Who* triaged is a Tier-2 user-auth
concern. We record `triaged_at` now and do **not** invent an actor. The clean
seam for it: triage writes go through a single repository upsert and a single API
handler — adding `triaged_by` is one nullable column (forward-only additive) plus
one parameter, with no read-path change. We deliberately do **not** add a
perpetually-null column today (no dead/fake schema).

## Consequences

**Easier**
- A `wont_fix` / `false_positive` disposition persists across runs: a later run
  producing the same `root_cause_key` shows the disposition immediately, so the
  dashboard can de-emphasise / hide muted issues instead of re-surfacing them.
- Triage is cleanly separated from the derived history and from per-result
  triage — three orthogonal axes, no overloading of `findings.status`.
- Idempotent upsert keyed on a unique pair → no triage races, no duplicates.

**Harder / watch-outs**
- A `root_cause_key` change (different anchor or failure signature) is, by
  definition, a *different* issue and starts fresh at `open`. That is correct —
  triage follows the identity — but means a disposition does not carry to a
  genuinely different failure shape.
- Until Tier-2 auth lands, dispositions are unattributed (`triaged_at` only).
  Stated in the API and UI rather than faked.
