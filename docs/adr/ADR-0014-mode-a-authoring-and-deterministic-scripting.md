# ADR-0014: Mode A authoring + deterministic-first scripting

- Status: Accepted
- Date: 2026-06-18
- Deciders: Engineering

## Context

The platform must support **Mode A** (Architecture §6): a human authors a test
case from scratch rather than having the AI plan it. Two questions:

1. **Where do authored cases live?** They must versioned like every other case
   (history, one-current, never-clobber). Option (a) a parallel "authored case"
   model/table; option (b) the existing `test_cases` lineage/versioning with a
   new `origin`.
2. **How is an authored case turned into a runnable Pest script?** The T1.4 path
   renders every case through the AI provider. But a structurally simple case
   (one endpoint, concrete method/URI/payload/expected-status + structural shape)
   is fully determined by the spec — calling a model to assemble it is needless
   cost, nondeterminism, and a flakiness surface.

Architecture §2/§5 mandate deterministic-first: AI only where it adds value.

## Decision

**Authored cases reuse the existing `test_cases` lineage/versioning** (no parallel
model). `CaseAuthoringService.create_case(project_id, spec, authored_by)` inserts
a fresh lineage at version 1, current, with a new origin value **`authored`**
(migration 0010, forward-only `ALTER TYPE ... ADD VALUE`, as in 0008) and
`edited_by_human=true`. Provenance reuses existing columns: `authored_by=human`,
the author in `edited_by`, the timestamp in `created_at`. Because the case is
human-edited from birth, **T3.2's clobber-protection already covers it** — a
re-generation matching its `case_key` can only propose, never overwrite. The
`case_key` is computed with the *same* function as generation when the case
targets a known endpoint+type (so re-generation recognizes it), else null
(free-form). Authored cases are edited afterward through the existing T3.1 edit
(append-only history), so there is genuinely one case model.

**Scripting is deterministic-first.** `render_authored_script` routes a simple
case to a pure **Pest template** (`deterministic=true`, generated_by=`template`,
no AI call); a case that needs app-specific knowledge — DB rows to set up, path
params, an unusual method — falls back to the existing **T1.4 AI render**
(`deterministic=false`). "Simple" is a deterministic predicate
(`is_template_renderable`): no DB setup, a known HTTP method, all path
placeholders resolved, no GET body.

## Consequences

**Easier**
- One versioning/merge/diff path for all cases (generated, edited, proposed,
  authored). Authored cases get never-clobber for free.
- Simple cases render with zero AI cost and are byte-for-byte reproducible — the
  template is a pure function of the spec.
- The simple/complex split is explicit and testable; the AI provider is provably
  untouched on the template path (call-count asserted in tests).

**Harder / watch-outs**
- `origin` now has four values; `authored` joins `generated|edited|proposed`.
  Forward-only — an added enum value can't be dropped without recreating the type.
- The template covers a deliberately narrow shape; broadening it (path params, DB
  setup) is future work, not a reason to widen the AI path.
- `edited_by` now records both the editor of an edit and the author of an
  authored v1; `origin` disambiguates which.

**Follow-ups**
- API endpoints + authoring UI (Sprint 6) over `create_case`.
- Grow the deterministic template (path params, declarative DB setup) to shrink
  the AI fallback further.
