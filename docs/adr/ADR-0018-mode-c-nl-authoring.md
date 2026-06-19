# ADR-0018: Mode C — natural-language test authoring

- Status: Accepted
- Date: 2026-06-19
- Deciders: Engineering

## Context

Mode C (PRD) lets a QA engineer author tests in plain English: "test the checkout
flow". The platform's discipline is **deterministic-first, AI only where it adds
value, with honest oracles**. Naively, an LLM could read the request and emit a
whole spec — but that puts the test's *meaning* (which page, which assertions,
their trust level) in the model's hands, exactly what we avoid elsewhere.

## Decision

Mode C is a thin pipeline with **a single non-deterministic edge**:

1. **NL → TestIntent (AI)** — an `AIProvider` proposes `{keywords, scenario_type}`
   from the request. The output is then **deterministically** post-processed and
   validated (`nl_intent`): keywords normalised/de-stop-worded, scenario type
   validated against a closed enum, with a deterministic fallback that extracts
   the intent straight from the NL when the model returns nothing usable (so the
   test stub — and a weak model — still yield a valid intent).
2. **TestIntent → journey (deterministic)** — keywords are resolved against the
   Brain (`BrainResolver`, vector + lexical with a lexical fallback) to pick the
   starting page, then `CrossLayerResolver` (T4.3) expands the cross-layer
   journey. No AI here.
3. **journey → cases (deterministic plan, AI only at the render edge)** — the
   existing T4.4 `e2e_generator`: deterministic plan, mutation-kill gate,
   oracle-honest assertions, AI renders only the spec. Persisted via the T3.2
   CaseMergeService lifecycle.

A thin `ModeCOrchestrator` (+ a factory for integration to wire) sequences these
and stamps provenance. AI touches ONLY the NL→intent edge and the spec render;
the journey, the plan, and every assertion's `oracle_source` are deterministic.

## Consequences

**Easier**
- One small, testable non-deterministic edge; everything downstream is
  reproducible and reuses audited components (resolver, generator, merge).
- A weak/canned provider still produces a deterministic intent, so the fast lane
  needs no real model.

**Harder / watch-outs**
- Resolution quality depends on the Brain being ingested; a low-confidence
  resolution should be surfaced for disambiguation (the resolver already flags
  it) rather than guessed — a follow-up for the UI.
- The intent vocabulary (scenario types, stop-words) is deliberately small; it
  will grow as Mode C is exercised.
