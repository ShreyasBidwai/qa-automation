# ADR-0041: Model node in the blast path + heal/findings reconciliation

- Status: Accepted
- Date: 2026-06-22
- Deciders: Engineering

## Context

Two honesty gaps in how findings surface, both additive follow-ups:

1. The finding location's cross-layer "blast path" rendered **page → endpoint →
   table**, but the signature path is **page → endpoint → MODEL → table**. The Brain
   already has model nodes and endpoint→model edges; the model layer was simply
   dropped on the way to the wire.
2. ADR-0040 flagged that a LOCATION failure **double-surfaces**: B8 proposes a heal
   for it AND the assembler turns the raw failing result into a Finding. Read
   together that says "the app is broken" when the honest story is "the test needs
   re-addressing."

## Decision

### (1) Surface the model node — a pure read, graceful when absent

The cross-layer `journey` already traverses endpoint→model→table, so model nodes are
**already in the resolved subgraph**; the assembler's `_location_payload` simply
extracts them now (`models`), and the detail/location payload carries them through.
No new query (no N+1) and no new edge walk — it is the same subgraph, read more
fully. When the endpoint→model edge is absent, `models` is just empty and the path
degrades to page → endpoint → table. The grouping anchor / `root_cause_key` ignores
`models`, so existing keys (and history classification) are unchanged. Findings
assembled before this change have no `models` key; the reader defaults it to empty.
Purely additive: more nodes in the same path structure.

### (2) Reconcile heals vs findings — tag everywhere, suppress in the inbox

A finding is **superseded by a heal** when its representative result's test case
carries an *active* heal (proposed or confirmed) in the same run. We chose
**tag + selective suppression** over either alone:

- **Tag** every finding with `superseded_by_heal` (additive). The run dashboard and
  single-finding views show every finding, tagged — the per-run view stays
  non-lossy.
- **Suppress** superseded findings from the **open-findings inbox** (the "what's
  broken" view) by default, so addressing drift doesn't read as a broken app. They
  remain reachable via the heals list (B8) and via an additive
  `include_superseded=true` query param (returned tagged).

The link is the heal's *existence*, which IS the confidence gate, so the safety
properties fall out for free:

- **An assertion finding is never suppressed.** B8 never proposes a heal for an
  assertion failure, so an assertion finding has no heal and can never be in the
  superseded set.
- **Low-confidence location failures stay findings.** B8 only proposes for a
  high-confidence re-binding; a low-confidence one has no heal, so its finding
  surfaces honestly.
- **A rejected heal un-suppresses.** Only `proposed`/`confirmed` heals mask a
  finding; once a human rejects the re-addressing, the failure stands as a real
  finding again.

Reconciliation is **read-time** — no new column, no migration. It costs two batched
reads (representative result → test case, the run's active heals) regardless of
finding count (no N+1).

### Additive while the UI is rebuilt

`models` on the location and `superseded_by_heal` on the finding are additive fields;
`include_superseded` is an additive query param (default preserves the "currently
broken" framing). No existing endpoint shape changes. What *surfaces* in the default
inbox changes by design (drift is excluded), but only for findings that have a heal —
a concept that didn't exist before B8.

## Consequences

- The blast-path ribbon shows the model layer when the Brain knows it, and silently
  shortens when it doesn't — no crash, no empty node.
- The inbox reads honestly: real findings (assertion + unhealed location) only;
  addressing drift is one click away (the heals list, or `include_superseded`).
- Suppression can never hide a real regression, because it is keyed on a heal that
  B8 only ever creates for a high-confidence, assertion-free addressing move.
