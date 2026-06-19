# ADR-0017: UI oracle model for generated E2E tests

- Status: Accepted
- Date: 2026-06-19
- Deciders: Engineering

## Context

The platform's differentiator is **oracle honesty**: every generated assertion
declares how much it is trusted, so a green suite means something. The backend
generator (T1.4) already tags each API assertion `rule-derived` (grounded in a
declared rule), `characterization` (recorded behaviour, weak), or `spec-grounded`
(a real requirement), and a mutation-kill gate rejects tautological assertions.

T4.4 generates **Playwright E2E** tests from cross-layer journeys. The same
question arises for the UI: an E2E test that merely asserts "the page loaded" is
worthless — it passes no matter what breaks. We must extend the oracle model to
UI assertions and keep the mutation-kill discipline, or UI coverage becomes
green-theatre.

## Decision

**Every E2E assertion carries an `oracle_source`, set deterministically by the
planner — never by the AI.** The AI renders the spec around the fixed plan; it
cannot add, weaken, or re-label an assertion.

UI oracle tiers (mirroring the backend):

- **rule-derived (strong)** — grounded in something the app *declares*. A form
  field with a `required` attribute → a negative case that leaves it empty and
  asserts the validation error. (Known response/redirect contracts will also be
  rule-derived once modelled.)
- **characterization (weak)** — recorded post-submit / rendered state (e.g. the
  happy path asserting a specific rendered indicator). Honest about being a
  snapshot of current behaviour, not a spec — upgraded to spec-grounded once a
  requirement is ingested.

**Mutation-kill gate (CI-enforced), two halves:**

1. *Static* (`enforce_mutation_gate`, fast lane): reject tautological assertions
   before a spec is rendered or persisted — a no-op kind ("loaded", "exists", …)
   or an empty target, and any case with no assertion at all.
2. *Runtime* (heavy `e2e_runner` lane): a generated spec runs against the fixture
   and passes, and a deliberately-wrong assertion is caught as a failure — the UI
   analogue of the backend mutant-kill test.

Generated E2E cases persist through the **T3.2 CaseMergeService** (deterministic
`case_key`, `origin=generated`, full provenance), so re-generation never clobbers
a human edit — a re-gen of a human-edited case becomes a proposal.

## Consequences

**Easier**
- A green E2E suite is meaningful: each assertion's trust level is explicit and
  the gate guarantees no assertion is a no-op.
- One oracle vocabulary spans API and UI; reporting/coverage can treat them
  uniformly.
- Re-generation is safe (never-clobber) for E2E exactly as for API cases.

**Harder / watch-outs**
- Without ingested specs, happy-path UI assertions are only `characterization` —
  honestly weak; the value grows when specs land (spec-grounded).
- The static gate catches obvious tautologies, not subtle ones (e.g. asserting an
  always-present element) — the runtime mutant-kill lane is the backstop.
- The AI must be held to "render only"; the provenance header + fixed plan in the
  context are how we keep assertions out of the model's hands.

**Follow-ups**
- Spec-grounded UI oracles once requirements are ingested.
- Model known redirect/response contracts as additional rule-derived assertions.
