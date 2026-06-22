# ADR-0040: Honest self-healing — heal the addressing, never the assertion

- Status: Accepted
- Date: 2026-06-22
- Deciders: Engineering

## Context

Most "self-healing test" tools quietly rewrite a failing test until it goes green.
That hides the exact thing a test exists to catch: when an assertion now fails
because the system regressed, "healing" it past the failure is actively harmful —
it launders a real bug into a green check. We want the useful half (a test that
breaks only because its target *moved* should follow the target) without the
dangerous half (a test that breaks because behaviour *changed* must stay red).

## Decision

### The deterministic spine: classify the failure, model-free (`app.healing.classify`)

A newly-failing, previously-passing test is split into exactly two classes by pure
pattern matching over the runner's failure text — no model:

- **LOCATION failure** — the test couldn't reach/resolve its target (a received
  `404`, "element not found", a selector timeout). The target likely moved → a
  candidate to heal.
- **ASSERTION failure** — the target was reached but the value/status/behaviour was
  wrong (`200`→`500`, a body mismatch, an expectation that didn't hold). A real
  finding → **never healed**.

The classifier is **biased toward ASSERTION**: a received 404 is the one
unambiguous location signal; an explicit assertion macro is checked before any
loose location keyword; everything ambiguous (including infra errors and empty
messages) falls through to ASSERTION. Under-healing is safe (a missed heal is just
a surfaced failure); over-healing is not. This split is the load-bearing safety
rule and is exhaustively unit-tested.

(To classify after the fact, the runner's failure detail is now persisted on
`results.message` — additive, nullable.)

### Heal the addressing, not the expectation — enforced structurally

On a location failure we re-resolve the moved target against the **current Brain**
(`app.healing.reresolve`): the test carries the route's stable identity
(`route_name`) in its preconditions; the re-ingested endpoint nodes carry the same
identity at the new URI. A single name match at a different URI is a high-confidence
re-binding; a same-method, same-last-segment match is a low-confidence structural
guess; anything else (deleted route, ambiguous, no code model) is **not** re-bound.
Re-resolution is deterministic; AI-assisted mapping for the genuinely ambiguous
middle is the labelled extension point, intentionally not wired into the spine.

The re-addressing itself (`app.healing.apply`) rewrites **only** the route literal
in the HTTP call and is forbidden from touching any assertion line. The guarantee
is enforced *structurally, not by convention*: `assertions_unchanged` independently
re-derives the assertion lines from the before/after code and requires byte
equality. The function that verifies the property is independent of the function
that makes the change, so a heal that would disturb an assertion is refused, not
trusted.

### Flagged, never silent — confidence-gated and human-confirmable

- Only **high**-confidence re-bindings are proposed; **low**-confidence ones are
  surfaced as unhealed failures (reported honestly, never auto-applied).
- A heal is recorded with before/after addressing, rationale, and confidence
  (`test_heals`), and is **proposed**, not applied: the live test is untouched until
  a human confirms. `status` is the trust marker — `proposed` is lower-trust,
  `confirmed` applies the re-addressing and restores trust, `rejected` discards it.
  Confirm/reject are RBAC-gated (`MANAGE_PROJECT`).
- The run scan reports an honest summary — **N healed (review), M real findings, K
  unhealed** — and is **idempotent**: the same `(test_case, before, after)`
  re-addressing is recorded once (a unique constraint), so re-scanning a run or a
  later run surfacing the same drift never duplicates a heal. The `case_key` is not
  recomputed by a heal, so a re-addressing is the same logical test, re-located.

### Additive while the UI is rebuilt

All surfacing is via **new** endpoints (`/runs/{id}/heal-scan`, `/heals`,
`/runs/{id}/heals`, `/heals/{id}/confirm|reject`). No existing run/finding response
shape changes. Suppressing healed location-failures from the findings list (so a
healed test stops showing as a bug) is a deliberate next step, kept additive for
now — today a location failure is both proposed as a heal and still visible as its
raw result, which is the honest, non-lossy default.

## Consequences

- The dangerous failure mode is structurally impossible: assertions cannot be
  healed, and the proof is an independent check, not a code-review promise.
- Healing is deterministic and confidence-gated, so it is fully unit-testable
  without a model, and a low-confidence guess is surfaced rather than applied.
- Every heal is reviewable and reversible; nothing goes green silently. A team sees
  "N healed (review), M real findings" and decides.
