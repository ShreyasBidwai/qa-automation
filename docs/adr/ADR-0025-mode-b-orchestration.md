# ADR-0025: Mode B orchestration + selection-strategy model

- Status: Accepted
- Date: 2026-06-19
- Deciders: Engineering

## Context

Mode B (PRD: autonomous; FR-8) is the hands-off loop: the platform decides what
to test, ensures cases exist, runs them, and produces findings with **no human in
the loop**. It is the capstone that ties the whole pipeline together — but it must
add *orchestration only*, reusing the components already built and trusted:
the generators (deterministic backend + E2E), the runners (`ExecutionRunner` via
`RunLifecycle`), the finding pipeline (assembler → severity → history), and the
T8.1 `ImpactSelector`. Reimplementing any of them here would fork behaviour.

Two things need deciding: (1) how Mode B chooses *what* to test, and (2) how it
stays honest when its scope is uncertain.

## Decision

**SelectionStrategy (pluggable, enum + factory — like the other providers).**
A `SelectionStrategy` yields a deterministic `Selection` (ordered `Target`s +
`scope_uncertain`):

- **FullSweep** — every testable node from the Brain (endpoints + pages), sorted
  `(kind, name, id)`. Never uncertain.
- **ChangeImpact** — wraps the T8.1 `ImpactSelector`: the impacted nodes that have
  covering cases become the targets, and the selector's `scope_uncertain` is
  propagated.

`build_selection_strategy(kind, …)` is the factory; ChangeImpact requires a
changeset + resolver (a typed `ModeBError` otherwise).

**ModeBOrchestrator.run(project, strategy, bounds)** sequences reused components:

1. **Select** targets via the strategy (deterministic order).
2. **Bound**: truncate to `max_targets`; an injected monotonic clock stops the
   ensure loop at `max_seconds`. Bounded by config, always.
3. **Ensure** a current case per target — *reuse* every existing current case for
   the target's node; only *generate* (via the injected `TargetGenerator`, which
   wraps the existing generators) where a target has **no** runnable case. Mode B
   never regenerates over an existing case, so human edits are never clobbered —
   the strongest never-clobber stance, and it leans on the existing versioning
   lifecycle rather than reimplementing merge policy.
4. **Execute** the gathered scripts through `RunLifecycle` + the injected
   `ExecutionRunner` (one run, mode `B`) — exactly as the walking skeleton does.
5. **Report** by reusing the finding pipeline: assemble → score → classify →
   rank. Returns a `ModeBRunReport` (run id, counts, strategy, fallback flag, the
   ranked findings).

**Honesty propagation (the core rule).** If the strategy reports
`scope_uncertain` (the T8.1 widen rule — a changed file mapped to no known node),
Mode B **discards the narrowed selection and runs a full sweep** instead. It never
executes a narrowed set when scope is uncertain; the report records
`full_sweep_fallback=True`. Widen, never narrow — the same ethos as ADR-0024,
propagated one level up.

Everything is deterministic (sorted targets, deterministic reuse order) and
project-scoped (every read/write is tenancy-filtered through the repositories).

## Consequences

**Easier**
- One autonomous entry point composes the whole pipeline without forking any of
  it; swapping selection strategy (full vs change-impact) is a one-line factory
  call, and CI can run change-impact with a safe full-sweep fallback.
- Testable in the fast lane end to end with a stub generator + stub runner — no
  real generation or browser — because every heavy collaborator is injected.

**Harder / watch-outs**
- `RunLifecycle` binds one runner per run, so a single Mode B run uses one
  `ExecutionRunner`; selecting pest-vs-playwright for a mixed-framework batch is a
  composition concern (and could become multiple runs) — deliberately not
  reimplemented here.
- "Ensure" only fills gaps; it does not regenerate stale cases (that is the
  clobber-risky path the merge/proposal flow already owns with protection). Mode B
  reusing a stale case is a recall trade-off, accepted for safety.
- A reused case needs a persisted script to run; a case with no script falls
  through to generation. Script→result mapping is by `test_case_id` (the persisted
  key), not the script file stem.
