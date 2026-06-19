# ADR-0020: Finding data model

- Status: Accepted
- Date: 2026-06-19
- Deciders: Engineering

## Context

A run produces `results` (one outcome per test case). The report a human consumes
is built from **findings** — bug objects with a title, where they live, how much
we trust them, and (later) severity, status, grouping, and history. T7.1 must fix
the **Finding contract** that the rest of Sprint 7 (grouping T7.2, scoring T7.3,
history T7.4) builds on, without disturbing the run/result pipeline.

Options for where findings live:

1. **Derive findings on the fly from results** at report time. No storage, but
   nothing to group/score/track across runs — T7.2–T7.4 would have no anchor.
2. **A new `findings` table** assembled from results. Persistent, queryable,
   groupable, and a stable contract; results stay untouched.

## Decision

**Add a new project-scoped `findings` table** (migration 0013, forward-only,
additive — `results` is not altered). A Finding references the `run` and the
`result` it covers and carries:

- `title`, `layer` (`ui|api|db` — a new `finding_layer` enum; where the bug
  manifests, distinct from how the case ran),
- `oracle_source` (the failing oracle's tier = the finding's **confidence**,
  reusing the existing enum),
- `expected` (the oracle's expectation; the **actual** is captured at
  `evidence_ref`, which the finding also carries),
- `location` (the cross-layer page→endpoint→table path, resolved from the Brain),
- `severity` and `status` **placeholders** (T7.3/T7.4 define the vocabularies).

A **`FindingAssembler`** builds one Finding per non-passing result for now
(grouping is T7.2): it reads the failing test case for the oracle/expected/layer
and resolves the cross-layer location from the case's target node via an injected
resolver (the `LocationResolver` slice of `CrossLayerResolver`). Passing results
produce nothing. A result whose case is not in the project raises
`FindingAssemblyError` (tenancy/integrity, never silently dropped).

## Consequences

**Easier**
- A stable, queryable anchor for T7.2–T7.4; grouping adds a join, scoring/status
  fill the placeholders — no schema churn to the contract.
- Results stay the immutable execution record; findings are a derived,
  re-assemblable view.
- Confidence is first-class on every finding (oracle_source), keeping the report
  oracle-honest end to end.

**Harder / watch-outs**
- One-finding-per-result is deliberately naive; T7.2 will group (e.g. the same
  bug across UI+API) — the `result_id` FK becomes a join then.
- The **actual** value is by-reference (evidence_ref), since `results` does not
  persist a per-assertion actual and this task must not alter it.
- `severity`/`status` are untyped placeholders until T7.3/T7.4; `finding_layer.db`
  is reserved (no case layer maps to it yet).
