# ADR-0013: Proposal resolution (accept / reject) with provenance

- Status: Accepted
- Date: 2026-06-18
- Deciders: Engineering

## Context

ADR-0012 made re-generation against a human-edited case append a **non-current
`proposed`, `proposal_status=pending`** version instead of clobbering the human's
edit. That deliberately left the human's current version in place and named the
follow-up: **resolution** — letting a human accept or reject the proposal.

Forces:

- **Never destroy the human edit.** Even when the human *accepts* the regeneration,
  their prior edit must remain in history — "accept the regen" is not "delete my edit".
- **One-current invariant.** Exactly one version per `(project_id, lineage_id)` is
  current, enforced by a partial unique index (T3.1). Accept changes which version
  is current, so the handoff must never produce two current rows, even transiently.
- **Terminal decisions.** A resolved proposal must not be re-resolved — re-accepting
  could demote the wrong current; re-rejecting could rewrite provenance.
- **Provenance.** Who decided, and when, must be recorded for audit/review.

Options for *where to promote the accepted content*:

1. **Copy the proposal into a new version, leave the proposal `accepted`.** Adds a
   redundant row; the proposal already carries the exact content to adopt.
2. **Promote the proposal row itself to current.** The proposal is already a real
   version in the lineage; flipping its pointer is the minimal, lossless change.

Options for *recording provenance*:

1. **Reuse `edited_by` + `updated_at`.** No schema change, but overloads
   `edited_by` (whose row stays `edited_by_human=false` after accept — the content
   is the AI's, not a human edit) and `updated_at` is a generic "last touched"
   that also bumps when the *other* row is demoted.
2. **Dedicated `resolved_by` + `resolved_at` columns.** Explicit, unambiguous,
   queryable; mirrors how ADR-0012 added a dedicated `proposal_status` rather than
   overloading the generic `status`.

## Decision

Add a **`ProposalResolutionService`** with `accept`, `reject`, and
`list_pending_proposals`, operating only on `origin=proposed` versions:

- **accept(project, lineage, proposal_version_id, accepted_by)** — **demote then
  promote**: set the current (human-edited) version `is_current=false` and flush
  (zero current rows), then set the proposal `is_current=true` (back to exactly
  one). The demoted human version is retained in history unchanged — only its
  pointer flips. The proposal becomes the new current; its content was already the
  AI's, so `authored_by`/`edited_by_human` are unchanged.
- **reject(...)** — set `proposal_status=rejected`; the proposal stays non-current
  (a dead version in history) and the human-edited current is **not touched at
  all** (still current, byte-for-byte unchanged).
- **list_pending_proposals(project)** — project-scoped, all lineages; the backing
  read for the future review queue (UI is Sprint 6).

**Resolution is terminal:** resolving a non-pending proposal raises
`ProposalAlreadyResolvedError`; a missing/foreign/non-proposal id raises the
existing `TestCaseNotFoundError`.

**Provenance** uses **dedicated nullable `resolved_by` + `resolved_at` columns**
(migration 0009, forward-only, additive). They are NULL on non-proposals and on
still-pending proposals, and are *not* carried forward by `new_version` (a fork is
a fresh, unresolved version). The promote-the-proposal-row approach is taken — no
redundant copy.

## Consequences

**Easier**
- The human edit is safe on both paths: reject never touches it; accept only flips
  its pointer, retaining it in history. The one-current invariant is preserved by
  demote-then-promote.
- Resolution is auditable (`resolved_by`/`resolved_at`) and idempotency-safe by
  being terminal.
- Composes with the T3.4 diff: `diff(current_human_version, pending_proposal)`
  shows exactly what accepting would change.

**Harder / watch-outs**
- Accepting promotes the proposal *as-is*; partial/field-level merge (take some of
  the regen, keep some of the edit) is intentionally out of scope — a later
  refinement on top of the diff.
- `resolved_at` is set in the service (app time) rather than via a server default,
  since it marks a business event on an existing row, not row creation.

**Follow-ups**
- API endpoints + review-queue UI (Sprint 6) over `list_pending_proposals`.
- Optional field-level merge using the structured diff.
