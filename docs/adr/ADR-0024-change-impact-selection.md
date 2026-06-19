# ADR-0024: Change-impact test selection — widen on uncertainty

- Status: Accepted
- Date: 2026-06-19
- Deciders: Engineering

## Context

Mode B / CI (PRD FR-8) wants to run only the tests a code change could affect, not
the whole suite — the differentiator over "run everything". The selection must be
**deterministic** (a diff selects the same tests every time), built over the Brain
we already have (no AI, no heuristic clustering), and — critically — **honest
about its own blind spots**, matching the oracle-honesty ethos. A selector that
silently under-selects is worse than no selector: it gives false confidence that
the untouched tests were safe to skip.

The primitives already exist: node **source provenance** (which file a Brain node
came from), `CrossLayerResolver.impact` (the 1-hop blast radius of a node), the
case→node **coverage** relation, and the read-only `GitProvider`.

## Decision

**ChangeSet.** A set of changed source file paths. The selector takes a ChangeSet
directly; a thin git-diff helper (`changed_paths`, over the same read-only command
runner the GitProvider uses — `git diff --name-only base..head`) can produce one
from two SHAs, but it is a separate seam, not part of selection.

**Source provenance.** A node's originating file is `attributes["source_file"]`.
The selector maps each changed file to the nodes that declare it. (The Laravel
ingester tags nodes with `source_sha` + `action`/`class`; normalizing those to a
`source_file` attribute is the ingestion-side contract this selector consumes —
selection's job is selection given provenance, not producing it.)

**Coverage.** A test case covers the node in its `target_node`. This is the
case→node "covers" relation; the `COVERS` edge kind is reserved for a future
case-node graph projection. Cases aren't Brain graph nodes, so coverage lives on
the case row.

**ImpactSelector** (deterministic, project-scoped, bounded):

1. **Map** each changed file → declaring nodes (the *seeds*). A changed file with
   no declaring node is an **unmapped** file.
2. **Expand** each seed through `CrossLayerResolver.impact` — its 1-hop blast
   radius (callers, written tables, gating roles). Seeds are "directly affected";
   their blast neighbours are "impacted via" the seed. The expansion is 1-hop and
   bounded (the resolver's contract); seeds are recorded before expansion so a
   direct hit is never downgraded to an indirect one.
3. **Select** the current cases whose `target_node` is in the affected set, each
   with a **rationale**: which changed file and (for indirect hits) which seed node
   pulled it in.

**Honesty — widen, never narrow (the core rule).** If any changed file maps to no
known node (a new/uningested file, config, infra), the selector does **not**
silently drop it. It records the file as **unmapped**, sets `scope_uncertain`, and
**recommends a full run** — even when other files did map and produced a non-empty
selection. The result always distinguishes **confidently scoped** (every changed
file mapped → run the selection) from **scope uncertain** (something didn't map →
run all). When uncertain, widen.

## Consequences

**Easier**
- CI runs a small, justified subset on a clean diff, with a per-case rationale a
  reviewer can audit — and falls back to a full run the moment the change touches
  something the Brain doesn't model. No false confidence.
- Pure and deterministic over stored data; trivially testable with injected
  nodes/edges/cases and the real `CrossLayerResolver`.

**Harder / watch-outs**
- Recall depends on provenance + coverage completeness: a node missing
  `source_file`, or an endpoint with no covering case, narrows the set — but an
  *unmapped file* is the safety net that forces a full run when provenance is
  absent. Mapped-but-uncovered changes are confidently scoped to zero tests (a
  coverage gap, surfaced elsewhere), not scope uncertainty.
- Expansion is 1-hop (the `impact` contract). A change whose effect propagates
  more than one hop is not chased transitively; this is a deliberate
  bound — widen the window later if recall demands, by ADR.
- `source_file` is the provenance contract; until ingestion populates it for every
  stack, real changes may read as unmapped and (correctly, conservatively) trigger
  full runs.
