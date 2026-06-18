# ADR-0012: Re-generation merge with clobber-protection (proposals)

- Status: Accepted
- Date: 2026-06-18
- Deciders: Engineering

## Context

The core Sprint 3 guarantee (PRD; Architecture §1; TRD §3): **re-generation must
never overwrite a human-edited case.** T3.1 made cases versioned with an
append-only history, an exactly-one-current invariant, and a `TestCaseService`
for human edits. But generation (T1.4) still wrote cases *directly* — every run
inserted new rows, so a second run would duplicate every case and had no notion
of "the same logical case," let alone of protecting a human edit.

Two problems had to be solved together:

1. **Identity across runs.** To reconcile a fresh generation against what exists,
   each generated case needs a stable identity that is the same every run for the
   same logical case, and different for a different rule/field.
2. **Reconciliation policy.** Given that identity, a re-generation must update
   AI-owned cases in place but leave human-edited cases untouched.

Options considered for the stable identity:

1. **Content hash of the generated case.** Changes whenever the generated payload
   changes — so a code change would orphan the old lineage and create a new one,
   defeating "match the same logical case."
2. **DB surrogate id.** Not derivable from a fresh plan, so a new run can't find it.
3. **Deterministic key from the plan** — endpoint + case type + targeted
   rule/field. Stable across runs, changes only when the logical case changes.

Options considered for reconciling a re-gen against a human-edited current:

1. **Skip / no-op.** Safe but silent — the new AI suggestion is lost; the human
   never sees that the code drifted from their edit.
2. **Overwrite or branch a new lineage.** Either clobbers the human edit or
   fragments history into parallel lineages for one logical case.
3. **Append a non-current proposal** in the same lineage, pending human review.

## Decision

**Generation no longer writes cases directly; all (re)generation persists through
a `CaseMergeService` keyed by a deterministic `case_key`** (migration 0008,
forward-only). Per generated case, matched by `(project_id, case_key)`:

- **no existing lineage** → create fresh: version 1, current, `origin=generated`.
- **current is AI-only** (`edited_by_human=false`) → append a new `generated`
  version and flip current (history preserved; AI cases track the code).
- **current is human-edited** (`edited_by_human=true`) → append a **non-current**
  `origin=proposed`, `proposal_status=pending` version linked to the lineage, and
  **do not touch the human-edited current**. This is the clobber-protection.

`case_key = "{METHOD} /{uri}::{case_type}::{name}"`, where `name` is the planner's
per-case identity (it already encodes field+rule uniquely — e.g. `size_below` vs
`size_above`, which share the coarse `rule` "size"). Pure function of the plan.

The `case_origin` enum gains `proposed`; a typed nullable `proposal_status`
(`pending|accepted|rejected`) column is added. The generic `status` column is left
to workflow state; the dedicated `proposal_status` is the authoritative proposal
lifecycle. **Resolution (accept/reject) is T3.3** — this sprint only creates the
pending proposal.

**Stale handling is deferred:** a lineage whose `case_key` is absent from a fresh
generation is left untouched (no stale-marking, no deletion) — the same
forward-only deferral as node deletion in T2.6 (ADR-0010 family).

## Consequences

**Easier**
- Re-running generation is idempotent-by-key: it matches existing lineages instead
  of duplicating them; re-gen of an AI case advances its version in place.
- Human edits are safe by construction: a re-gen against a human-edited current
  can only ever *append a non-current proposal*; the human version is never
  mutated or demoted (it stays the sole current row — the one-current DB invariant
  is untouched because proposals are non-current).
- The proposal carries the AI's latest content, so T3.3 can diff/accept/reject it.

**Harder / watch-outs**
- `case_key` must stay deterministic and collision-free; it is carried forward
  across versions (edits never change it). A bad key would either duplicate
  lineages (under-match) or merge distinct cases (over-match → surfaced loudly as
  a `MergeError` when one key resolves two current lineages).
- `case_key` is nullable for rows predating keying; those won't be matched (a
  one-time gap, acceptable and forward-only).
- Re-gen against an AI-only case appends a version even when content is unchanged;
  per-content dedup is a later optimization (SHA cache, ADR-0010), not correctness.

**Follow-ups**
- T3.3 proposal resolution: accept (promote proposal to current, retire the human
  version) / reject (mark `rejected`), with provenance.
- Stale-marking of lineages absent from a fresh generation.
