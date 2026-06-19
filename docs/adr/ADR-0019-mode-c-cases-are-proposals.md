# ADR-0019: Mode-C generated cases are proposals

- Status: Accepted
- Date: 2026-06-19
- Deciders: Engineering

## Context

Mode C generates test cases from a natural-language request the human just typed.
Unlike backend re-generation (which tracks the code and may own AI cases
outright), Mode-C output is a *suggestion the human asked for* and should land in
a review posture — and it must never overwrite work a human has already edited.

The T4.4 `e2e_generator` persists through the T3.2 `CaseMergeService`, which tags
a net-new or AI-only case `origin=generated` and only produces `origin=proposed`
when it is protecting a human-edited case. Mode C wants *all* its output to be
proposals. The Sprint-5 coordination contract forbids editing the shared
generator or merge service.

## Decision

Reuse the e2e_generator/CaseMergeService pipeline **unchanged**, then, in a new
Mode-C file, **re-tag** the net-new/updated cases it produced as
`origin=proposed`, `proposal_status=pending`:

- a fresh or AI-only case (merge action `created`/`updated`) → re-tagged to a
  pending proposal (it becomes the current, but-pending case the human reviews);
- a re-gen that hit a **human-edited** case (merge action `proposed`) is ALREADY
  a non-current pending proposal from the merge engine and is left exactly as-is
  — **the human's version is never touched** (the never-clobber guarantee comes
  straight from CaseMergeService).

Proposals therefore flow into the existing T3.3 review/accept-reject lifecycle
(`list_pending_proposals` surfaces them; accept/reject resolves them). Provenance
(the NL request, intent keywords, scenario type) is stamped on each case's
existing `preconditions` jsonb — **no new column, no migration**.

## Consequences

**Easier**
- Mode-C output is uniformly reviewable: one proposal lifecycle (T3.3) for both
  re-generation and NL authoring; nothing auto-adopts.
- Reuses the audited generator + merge + never-clobber rule without forking them;
  the only Mode-C-specific step is a deterministic re-tag.

**Harder / watch-outs**
- A net-new Mode-C proposal is `is_current=true` *and* `proposal_status=pending`
  — a "current but pending" case. This is intentional (it is the working case
  until reviewed) but is a slightly different shape from a re-gen proposal
  (non-current); resolution handles both (accept on a current proposal is a
  no-op promotion).
- Re-tagging happens after the merge write; it is a post-step in Mode-C code, not
  a change to the shared merge engine.
