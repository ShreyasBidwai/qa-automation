# ADR-0038: Business documents → the Brain + spec-grounded oracles

- Status: Accepted
- Date: 2026-06-22
- Deciders: Engineering

## Context

The Brain is built from code (endpoints/models/tables). Generated oracles are
therefore only `rule-derived` (from validation rules) or `characterization` (pins
current behavior). The strongest tier — `spec-grounded` (blue) — needs a documented
contract to anchor to. B9 lets a project attach business documents (requirements,
API contracts, user flows, acceptance criteria) and uses them to ground oracles.

## Decision

### A per-project document store, embedded into the same vector space

- `project_documents` (title, kind, content) and `document_chunks` (ordinal, text,
  `embedding vector(384)`), project-scoped, RBAC-gated (member+ to mutate; any
  member to read). Chunking is deterministic (`chunk_text`); embedding reuses the
  **local fastembed** provider (no API cost), batched (one provider call per
  document — no N+1). Chunk vectors share the **same 384-dim space + HNSW cosine
  index** as `model_nodes`, so retrieval works identically.
- **A separate store, not `model_nodes`.** The code Brain is "rebuildable from the
  codebase"; user docs are not, and a code re-ingest must not wipe them. Keeping
  docs in their own tables preserves that invariant while still living in the same
  embedding space (retrieved the same way).

### Spec-grounded oracles — honest + deterministic

At generation, `SpecGroundingService` embeds the target endpoint, retrieves the
top-k relevant chunks, and upgrades a case's `oracle_source` to `spec-grounded`
**only when the case's specific field is actually documented** in those retrieved
chunks (a word-boundary match). It is NOT upgraded merely because the project has
documents, nor on fuzzy semantic proximity alone — the field must appear in a
relevant chunk. Semantic retrieval narrows the candidate set; a deterministic
lexical check confirms the grounding. AI still only *renders*; grounding is
retrieval + a pure check.

## Consequences

- Docs are embedded locally and free; grounding is honest (real doc basis) and
  deterministic (no model in the tagging decision), so it's exhaustively testable.
- The code Brain stays code-derived and rebuildable; docs are a parallel, unified
  retrieval surface.
- Spec-vs-code reconciliation (ADR-0039) runs on the same ingest.
