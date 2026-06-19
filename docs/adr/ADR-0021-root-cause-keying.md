# ADR-0021: Root-cause keying — what makes two failures the same bug

- Status: Accepted
- Date: 2026-06-19
- Deciders: Engineering

## Context

T7.1 emits one Finding per failing Result. A real run produces many failing
results that are the *same bug* — twelve UI journeys that all break because one
endpoint 500s, or every test touching a corrupt table. A report that lists those
as twelve separate findings buries the signal. T7.2 must collapse failures that
share a **root cause** into a single Finding that "explains N tests", and drop
literal duplicate failures within a run.

"What makes two failures the same bug?" is a judgement call with no free lunch:

- **Too coarse** (e.g. group by run, or by layer) merges unrelated bugs.
- **Too fine** (e.g. group by test case) is just T7.1 again — no grouping.
- It must be **deterministic** (same run → same grouping, every time) and derived
  only from data already on the Result, the failing TestCase, and the Brain
  (no AI, no clustering) so it is explainable and reproducible.

## Decision

Each failing Result gets a deterministic **`root_cause_key`** = `anchor # signature`:

**1. Anchor — the *where* (deepest shared failing node).** From the Result's
cross-layer location (the page→endpoint→table journey resolved from the failing
case's target node via `CrossLayerResolver`), take the **deepest layer present**,
in order **table → endpoint → page**:

- `table=<sorted,comma-joined table names>` if any tables are in the journey,
- else `endpoint=<sorted,comma-joined endpoint names>`,
- else `page=<page name>`,
- else `unlocated`.

The deepest layer is the *most likely culprit*: if a table is broken, every
endpoint reading it and every page calling those endpoints fail — they share the
table, so they share a finding. Anchoring on the deepest shared node is what lets
twelve UI failures collapse into "the orders endpoint is down". Names are sorted
and joined so the anchor is a stable set, not an arbitrary pick.

**2. Signature — the *how* (failure shape).** `outcome` (`fail`/`error`) plus, when
present on the failing case's `expected` oracle, the expected `status` and the
sorted set of assertion `kind`s. Two failures at the same node but with different
failure shapes (a 500 vs a wrong-body assertion) are *different* bugs and stay
apart.

**Confidence of a group** = the **strongest `oracle_source`** among its members
(`spec-grounded` > `rule-derived` > `characterization`). One rule-derived failure
makes the whole group trustworthy — a real rule was violated, regardless of how
many weak characterization oracles rode along. A group whose members disagree on
oracle tier is flagged **`confidence_mixed`** so the report can say "high
confidence, but some members are characterization-only".

**Dedupe.** Within a group, results are deduped by **`test_case_id`** (the
deterministic-first kept): the same logical test failing twice in a run (a re-run,
a flake) is *one* explained test, not two. `explains_count` = the number of
distinct test cases in the group.

One Finding per `(run_id, root_cause_key)` — enforced by a unique index. The
representative Result (deterministic-first) is retained on the Finding (T7.1's
`result_id` contract is kept); the full set is recorded in the `finding_results`
join (ADR migration 0014).

## Consequences

**Easier**
- The report shows N real bugs, each explaining M tests, instead of M×N rows.
- Grouping is pure, deterministic, and explainable from the key string itself —
  no model, no nondeterministic clustering; re-assembly is idempotent.
- Confidence is computed honestly: a group is as trustworthy as its strongest
  oracle, and mixed groups say so.

**Harder / watch-outs**
- Anchoring on the *deepest* node deliberately groups across endpoints that share
  a broken table. That is the intended root-cause semantic, but it can over-group
  if two endpoints touch the same table for unrelated reasons — acceptable for
  now; a future refinement can weight by edge confidence.
- The signature is only as rich as `expected`; a thin oracle yields a coarse
  signature (just `outcome`). It degrades safely (more grouping), never crashes.
- `root_cause_key` is a stored, queryable contract now (it orders findings and
  keys the unique index). Changing the keying rule is a re-keying migration, so
  it is fixed here by ADR.
