# ADR-0059 — Layer-scoped "Describe it" (NL→UI/API) + authored-proposal review

## Status

Accepted.

## Context

"Describe it" (Mode C) turned a natural-language prompt into a **UI page-journey**
E2E test (`app/modes/mode_c.py`: NL → intent → resolved page → Playwright spec). That
was the *only* thing it could author — there was no way to describe an **API contract**
test ("orders reject an unauthenticated POST") in plain English and get endpoint tests.

The UI implied the two run modes were peers ("Describe it" vs "Autonomous"), but only
Autonomous (Mode B) exposed a UI/API/DB layer scope. Users reasonably asked "why can't
I pick a layer when I describe a test?" — the honest answer was that Describe-it was
UI-only.

Two more gaps compounded it:

- **Nowhere to land.** After a Describe-it submit the UI navigated to a live-run view,
  but Mode C authors cases and produces **no run/findings** — so the operator stared at
  an empty run instead of seeing the tests just authored.
- **No human gate.** Mode C already tagged its cases `origin=proposed`,
  `proposal_status=pending` ("the human review queue"), but no API or UI existed to
  accept or discard them, so authored proposals silently became live tests.

## Decision

**1. A layer on Mode C.** `ModeCRunRequest` gains `layer: "ui" | "api"` (default `ui`,
preserving existing behaviour), threaded through `RunRequest` → the durable job
payload → the executor. `_run_mode_c` dispatches:

- `ui` → the existing page-journey orchestrator (unchanged).
- `api` → a new `ModeCApiOrchestrator` (`app/modes/mode_c_api.py`): `parse_test_intent`
  → `BrainResolver.resolve` (the same embedding retrieval the UI path uses, filtered to
  the top **endpoint** node) → `endpoint_spec_from_node` → the **same** `TestGenerator`
  Mode B runs for that endpoint. So API authoring is grounded in the endpoint's real
  contract and can't invent assertions — it reuses proven components, adds only the
  NL→endpoint resolution.

To avoid an `api`⇄`modes` import cycle, the pure `endpoint_spec_from_node` helper moved
from `app.api.real_execution` to `app.generation.endpoint_from_node` (re-exported from
its old home for backward compatibility).

**2. Authored cases are proposals.** Both Mode C paths persist as `origin=proposed`,
`proposal_status=pending` (via `generate_proposed_cases` / `generate_proposed_api_cases`).
A new `CaseReviewService` + endpoints (`POST …/tests/{id}/accept|/discard`,
MANAGE_PROJECT) resolve one pending proposal:

- **accept** → `proposal_status=accepted`; the case stays current and runs.
- **discard** → `proposal_status=rejected` + `is_current=false`; it drops out of the
  viewer (`list_current`) and run selection, but the row survives for provenance.

This is deliberately distinct from `ProposalResolutionService` (regeneration-vs-human-
edit conflicts). These are net-new authored cases with no prior current version, so
review is a simple in-place status transition — no lineage surgery.

**3. Land on the Tests viewer.** A Describe-it submit navigates to
`/projects/{id}/tests?authoring=<jobId>`. The viewer polls that job
(`useAuthoringJob`), shows an "authoring…" banner, and reloads the list on success —
so the freshly-authored proposals appear on their own, each with Accept/Discard.

CSV import (ADR-0058) stays `origin=authored` (not proposed): the QA specified those
tests exactly, so they don't need a review gate — the review flow is for AI-authored
proposals.

## Consequences

- A QA can describe an API-contract test in plain English, not just a UI journey; the
  two authoring engines coexist and are chosen with one toggle.
- Nothing AI-authored goes live unreviewed — the human accepts or discards each
  proposal, and sees them the moment they're written.
- API authoring depends on the endpoint being in the Brain (ingested). If the
  description resolves to no endpoint node, the run fails with a clear message (surfaced
  by the authoring banner) rather than authoring nothing silently.
- DB-layer NL authoring is intentionally deferred (a state-invariant authoring engine
  is a larger, separate design); the toggle offers UI + API only.
