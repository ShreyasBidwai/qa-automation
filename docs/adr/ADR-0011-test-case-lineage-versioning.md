# ADR-0011: Test-case lineage versioning (append-only history, one current)

- Status: Accepted
- Date: 2026-06-18
- Deciders: Engineering

## Context

`test_cases` provenance/versioning is a **frozen contract** (TRD §3, §14): human
edits must create a new version with `edited_by_human=true`, and re-generation may
produce a sibling version but **must never supersede a human-edited head** — the
"re-generation never clobbers human edits" requirement (PRD; Architecture §1).

The Sprint 1 schema (T1.1) carried the building blocks — `version`,
`parent_version_id`, `edited_by_human`, `authored_by`, `oracle_source` — and a
`new_version` repository helper that forks a row without mutating the prior one.
What it lacked was a way to (a) identify *all versions of one logical case* as a
group, and (b) name *the* current version cheaply and safely, enforced so no code
path (or concurrent writer) can produce two heads.

Options considered for "which versions form one logical case, and which is current":

1. **Walk `parent_version_id` chains.** No extra columns, but every "current" or
   "history" read becomes a recursive walk, and "is this the head?" has no
   cheap, enforceable answer — two heads can silently coexist.
2. **A separate `case_heads` pointer table** (one row per logical case → current
   version id). Enforceable via PK, but adds a table and a write to keep in sync
   on every edit; the head/version split invites drift.
3. **`lineage_id` + `is_current` on the row, with a partial unique index.** Each
   version row carries the lineage it belongs to and a boolean head flag; a
   partial unique index `(project_id, lineage_id) WHERE is_current` makes "exactly
   one current per logical case" a database invariant, not a convention.

## Decision

**Extend the `test_cases` contract additively with a lineage model (option 3).**
New columns (migration 0007, forward-only):

- `lineage_id` — every version of one logical case shares it; a fresh root gets a
  new lineage, a fork carries its parent's lineage forward.
- `is_current` — the single current-version pointer.
- `origin` (`generated` | `edited`, enum `case_origin`) — per-version provenance:
  what produced *this* row, distinct from `authored_by` (original authorship,
  carried forward unchanged across edits).
- `edited_by` — editor identity for edited versions; the edit timestamp is the new
  row's own `created_at`, so no separate column.

**Exactly one current version per `(project_id, lineage_id)` is enforced by a
partial unique index** (`uq_test_cases_one_current … WHERE is_current = true`),
not by application logic.

**History is append-only and immutable.** An edit forward-copies the current
version's fields, applies the changes, and APPENDS a new version; prior versions'
content is never mutated or deleted. The only write to a prior row is flipping its
`is_current` pointer to false — done *before* the new current is inserted so the
partial unique index is never transiently violated. Edit policy lives in
`TestCaseService`; the repository helper stays mechanical and creates forks
non-current by default so it cannot itself produce a second head.

`oracle_source` is carried forward as-is unless an edit changes the oracle; a
"human-vouched" oracle tier is a deliberate later refinement.

Backfill: existing rows become `version 1` / current of their **own** lineage —
achieved by adding `lineage_id` with a volatile `gen_random_uuid()` default (one
distinct lineage per existing row) and `is_current` defaulting true; verified on a
populated table.

This implements the existing TRD §3 versioning rule; it does **not** change its
semantics. The re-generation **merge/diff** behaviour (sibling version vs.
human-edited head) is recorded by that rule and lands in a later Sprint 3 task —
this ADR provides the lineage substrate it will build on.

## Consequences

**Easier**
- `get_current` / `get_history` / `get_version` are plain indexed, project-scoped
  reads — no recursive chain walks.
- The never-clobber invariant is correctness-by-construction: the DB rejects a
  second current head, so no edit, re-generation, or race can create one.
- Per-version provenance (`origin`, `edited_by`, `edited_by_human`,
  `parent_version_id`, `created_at`) is complete and queryable; AI v1 is preserved
  verbatim in history when a generated case is edited.

**Harder / watch-outs**
- The current-pointer handoff is order-sensitive: retire the old head *before*
  inserting the new one (the partial index is non-deferrable). Centralised in the
  service so callers don't reimplement it.
- `is_current` is the one mutable field on an otherwise immutable row; "immutable
  history" means *content* immutability — the pointer (and its `updated_at`) may
  flip. Tests assert content byte-for-byte unchanged and the pointer flip
  separately.

**Follow-ups**
- Re-generation merge logic (Sprint 3, task 2): a re-gen produces a sibling in the
  lineage and surfaces a diff/merge against a human-edited head, never overwriting.
- CRUD API endpoints over this service (`GET/POST/PATCH /test-cases`,
  `POST /test-cases/:id/lock`) with Pydantic boundary validation.
