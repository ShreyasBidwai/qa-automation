# ADR-0037: Generated tests are directly runnable — extract code, and skip (not break) on missing factories

- Status: Accepted
- Date: 2026-06-22
- Deciders: Engineering

## Context

The B5→B6 smoke ran the real AI generator against the Laravel fixture and surfaced
two reasons a freshly-generated test was not directly runnable:

1. **Markdown/prose wrapping.** A real model returns the test wrapped in lead-in
   prose, a ```` ```php ```` fence, and a trailing "Key decisions" table. The
   persisted "script" therefore contained prose + fences and was not valid PHP. The
   hermetic suite missed it because the test stub returned *clean* code — the one
   shape a real model never produces. (PHP additionally only treats text after
   `<?php` as code, so the deterministic provenance header was being emitted as raw
   output, not a comment.)
2. **Missing factories.** The model writes idiomatic Laravel — `Model::factory()` —
   but a target may define no factories, so the test *hard-fails* on the missing
   factory (an execution error, not a real finding). Seeding arbitrary preconditions
   is a real feature, parked as **B10**; we just must not emit broken tests now.

## Decision

### Code extraction + a code-only prompt (belt and suspenders)

`extract_code` (deterministic, pure, exhaustively unit-tested) recovers the
executable code from however the model wraps it — a fenced block (one or many; the
largest code-looking block wins), an unlabelled fence, or no fence (lead-in prose is
dropped). `with_php_header` then assembles a **valid** PHP file: `<?php` first, the
provenance header as real PHP comments after it. The generation prompt is also
tightened to demand code-only output (no fences, no prose) — defense in depth, so
there is ideally nothing to strip. A **prose-wrapping stub** is added to the
hermetic suite so this can never regress: the suite now proves extraction yields a
runnable script from messy, model-shaped output.

### Missing factories → honest skip, not a broken test

`target_has_factories(repo)` is a deterministic filesystem check
(`database/factories/*.php`). When a target has **no** factories:

- the prompt steers the model off `::factory()` (use explicit inserts / seeded
  data), and
- as a belt, `skip_if_uses_factory` deterministically chains `->skip(reason)` onto
  any residual factory-using Pest test, so it is reported **skipped** (honest,
  visible) instead of erroring on a missing factory.

When factories exist, behaviour is unchanged.

### Why skip rather than seed

Generating correct precondition seeding for arbitrary endpoints is exactly the work
scoped to **B10**. For this bridge, an honest skip is strictly better than a broken
test: it produces no false error and no spurious finding, it's visible to the
operator, and it's trivially reversed once seeding lands. The provider stays
pluggable and the plan/render split stays deterministic-first — extraction and the
factory guard are pure transforms over the model's output, not new model behaviour.

## Consequences

- A real run now persists **directly-runnable** Pest/Playwright tests; the smoke's
  prose-wrapping gap is closed and guarded by a regression stub.
- On factory-less targets, factory-dependent cases are skipped (not broken);
  everything else runs. Deep seeding is B10.
- `render_script` is now correctness-critical for runnability, so it (and
  `extract_code`) carry the heaviest unit coverage in the generation layer.
- The smoke's 404 was a *hand-built-spec* artifact (the spec's URI/auth didn't match
  the route); the real path derives the `EndpointSpec` from ingest (`route:list`),
  asserted hermetically — no code change needed there.
