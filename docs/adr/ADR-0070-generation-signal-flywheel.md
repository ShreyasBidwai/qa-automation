# ADR-0070 — GenerationSignal: the self-improvement flywheel's capture spine

## Status

Accepted. First slice of Initiative C (the data flywheel). The foundation the later
loops read from: self-repair telemetry (C3), retrieval exemplars (C4), eval metrics +
dashboard (C5/C6).

## Context

We want the product to get better at generating tests the more it runs — without
owning or fine-tuning a model (we consume Claude via `claude -p` / the API, so there is
no weight to train). The realistic mechanism is a **data flywheel**, and the unlock is
that **our test outcomes are free labels**: a generated test that ERRORs is an
objectively bad generation; one the human rejects in triage is a bad oracle; one that
heals is brittle. Execution + triage are the annotators. But that signal is scattered
across `results`, `findings`/triage, `test_heals`, and never joined to the *input
context + the prompt/strategy version that produced the artifact* — so it can be neither
measured nor learned from.

## Decision

Introduce one append-only capture table, **`generation_signals`**, that joins a
generated artifact's INPUT to its OUTCOME:

- INPUT / feature space: `route_class` (web/api), `framework`, `target_kind`, plus the
  **generation version** — `prompt_version`, `strategy`, `model`, `provider`. Versioning
  is load-bearing: without it a quality change cannot be attributed to a prompt change vs
  the model vs the customer mix.
- OUTCOME / free labels: `outcome` (pass/fail/error/skipped, NULL until executed),
  `repaired` (needed a self-repair pass), `healed` (brittle), `flaky`, `triage`
  (accepted/rejected — the human label on oracle quality), and a `detail` JSONB.

Like `ai_usage`/`incidents`, it is an **observability log**: keyed by
`project_id`/`run_id` with NO foreign key (it must outlive the entities it references),
never mutated after write. This single log is simultaneously:
- the **eval set** — quality is now measurable (pass-without-repair rate, error rate,
  false-positive rate from triage, heal/flake rate), segmented by version;
- the **retrieval corpus** — known-good rows (`outcome='pass'`, not repaired, not
  rejected) are the few-shot exemplars for RAG-augmented generation (C4);
- the **training/optimisation basis** — prompt/strategy A/Bs are judged against it (C5).

`GenerationSignalRepository` exposes `record()` and `quality_summary(since, version?)`
(the eval aggregate). The metric that must NOT be optimised alone is pass-rate — a
composite (passes AND finds real bugs AND low false-positive AND low repair/heal) is the
only honest target; the SKIPPED outcome (ADR-0064) and triage are what stop the system
gaming green.

## Consequences

- Capture is deliberately decoupled from the write path here (model + repo only); the
  generation/execution seams populate it in C2 (versioning) and C3 (self-repair), and
  triage/heal backfill the labels — so this slice is additive and risk-free.
- Privacy (the cross-tenant learning landmine): the corpus stores structure/labels, not
  a tenant's source or secrets; cross-tenant exemplar sharing is opt-in and abstracts to
  pattern (route shape, assertion idiom), never raw code (a later slice enforces this).
- "One run improves us" is true at the flywheel layer: each run appends validated rows
  that immediately sharpen retrieval + shift the eval metrics — not by moving model
  weights (which no single run can), which is the honest version of the ambition.
