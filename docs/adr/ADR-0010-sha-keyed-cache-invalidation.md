# ADR-0010: SHA-keyed cache invalidation

- Status: Accepted
- Date: 2026-06-17
- Deciders: Engineering

## Context

Almost everything the platform produces is **derived from target code**: model
nodes/edges (the Brain), embeddings (T2.3), extraction results (`EndpointSpec`),
and AI-rendered artifacts (generated tests, triage). These are expensive to
recompute and must stay correct when the code changes — a stale node or
embedding silently poisons generation and resolution.

Two needs point at the same mechanism:

- **Caching:** avoid recomputing derived artifacts that haven't changed
  (re-ingest, re-embed, re-generate should be incremental — TRD §7 says re-index
  is incremental on changed files).
- **Change-impact:** when code changes, find and re-run exactly the tests/subgraph
  affected (a core product capability — TRD §1/§4, run trigger `change-impact`).

Both reduce to: *given a code change, which derived artifacts are now invalid?*
Maintaining two separate invalidation schemes would risk them disagreeing — a
cache that thinks something is fresh while change-impact thinks it changed.

The schema already carries the hook: `model_nodes.source_sha` (this sprint), and
the same column pattern will extend to embeddings and other derived rows.

Options considered:

1. **Time/TTL-based invalidation.** Wrong primitive: code correctness is not a
   function of wall-clock time; TTLs either over-recompute or serve stale data.
2. **Manual/explicit invalidation.** Error-prone; easy to forget a dependency and
   serve a stale subgraph.
3. **Content/commit-SHA keying.** Key every derived artifact by the SHA of the
   source content (or commit) it was derived from. A code change changes the SHA,
   which invalidates exactly the artifacts derived from it — and the *same* SHA
   delta drives change-impact selection.

## Decision

**Key anything derived from code by its source content/commit SHA.** A change to
the source changes the SHA, which invalidates that artifact's subgraph; the
**cache and change-impact share this one invalidation mechanism**.

This is a **recorded decision**; implementation lands when there is something
worth caching — i.e. after embeddings (T2.3) and generation/run re-execution
exist and incremental re-runs become valuable. The `source_sha` column on
`model_nodes` is the first concrete carrier of this key (and `derived_from`
edges, plus the per-artifact SHA columns to come, express the dependency graph
the invalidation walks). **Do not build the cache layer now (YAGNI).**

## Consequences

**Easier**
- One invalidation model for caching *and* change-impact — they cannot disagree.
- Correctness-by-construction: a stale artifact is impossible if its SHA no
  longer matches its source; re-computation is naturally incremental.
- The Brain stays rebuildable (Architecture §7): SHAs make a partial rebuild safe.

**Harder / watch-outs**
- Requires capturing the right SHA granularity (per-file content vs commit) and
  recording each derived artifact's source dependencies (`source_sha`,
  `derived_from` edges) so invalidation can walk them.
- Cross-artifact dependencies (e.g. an embedding derived from a node derived from
  a file) must propagate SHA changes transitively — the dependency graph must be
  complete or invalidation under-fires.

**Follow-ups**
- When embeddings/generation re-runs exist, a follow-up will specify the SHA
  granularity, the dependency-propagation walk, and how `change-impact` run
  selection consumes the same keys.
