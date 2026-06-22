# ADR-0039: Spec-vs-code reconciliation — concrete, high-confidence, non-adjudicating

- Status: Accepted
- Date: 2026-06-22
- Deciders: Engineering

## Context

Once a project attaches business documents (ADR-0038), the docs and the code can
disagree: a contract references an endpoint the code doesn't have, or vice-versa.
That disagreement is valuable — but only if surfaced **honestly**. Two failure
modes to avoid: (1) false positives from fuzzy prose ("users can check out" is not
a claim about a route), and (2) auto-adjudicating which side is wrong (a stale doc
and a real code gap look identical to a static pass — a human must decide).

## Decision

### What we flag

On document ingest, a **static, deterministic** pass extracts only **concrete HTTP
route references** — an explicit `METHOD /path` (a strict regex). That regex IS the
confidence gate: prose without that exact shape never matches, so we never flag a
vague sentence. Each concrete reference is checked against the code Brain's endpoint
nodes (`model_nodes`, kind=endpoint). A referenced route **absent** from the Brain
is recorded as a `spec_divergences` row:

- `kind = endpoint_missing`, `confidence = high`, `status = open`,
- `spec_reference` = "X" (what the doc says, e.g. `POST /widgets`),
- `code_observation` = "Y" (what the code shows, e.g. "no matching endpoint"),
- `excerpt` = the surrounding doc text.

### What we do NOT do

- **No adjudication.** Both sides are tagged; the row says "spec says X, code shows
  Y" and stops. Stale-doc vs real-gap is a human triage decision.
- **No flag without a code model.** If the Brain has zero endpoints (code not
  ingested), we reconcile against nothing and flag nothing — we cannot honestly
  claim "code lacks X" when we have no code.
- **Field-level reconciliation is deferred.** Field references in prose can't be
  flagged at high confidence without false positives; endpoint-level is the concrete
  signal for now.

### Surfacing

A distinct, project-scoped signal — `GET /projects/{id}/spec-divergences` (VIEW),
separate from run findings (these are doc-vs-code, not test results). Divergences
cascade-delete with their document.

## Consequences

- High-signal, low-noise: only concrete, high-confidence divergences; fuzzy prose is
  guarded out (and tested).
- The operator/team sees both sides and decides; Polaris stays honest about not
  knowing which is correct.
- Deterministic + no AI → fully unit-testable; runs batched on ingest.
