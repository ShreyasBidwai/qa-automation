# TRD — QA Automation Platform

*Status: baseline (v1). Companion to `01-architecture.md`, `02-prd.md`, `04-engineering-standards.md`. Schema, interfaces, and security model here are contracts — change via ADR.*

---

## 1. Scope

Technical specification for v1: data model, API surface, core interfaces, AI/Brain/execution design, async/queue, security, observability, deployment. Implements the architecture and PRD.

## 2. Tech stack & versions

- Python 3.12, FastAPI, Uvicorn, SQLAlchemy 2.x, Alembic, Pydantic v2 / pydantic-settings, pytest, ruff, black, mypy.
- Node 20, React 18, Vite, TypeScript 5, Tailwind, shadcn/ui, Radix, TanStack Table, Recharts, Vitest, Playwright, eslint, prettier.
- Postgres 16 + pgvector.
- Docker + Compose; GitHub Actions.
- AI: pluggable provider; dev impl shells to `claude -p`.

## 3. Data model (contract)

Every table carries `project_id` (FK → `projects`) and standard audit columns (`id` UUID, `created_at`, `updated_at`). Tenancy is enforced at the query layer.

**Core tables:**
- `projects` (id, name, slug, settings json).
- `repos` (project_id, provider, url, default_branch, last_indexed_sha, access: read-only token ref).
- `model_nodes` (project_id, kind: endpoint|page|model|table|role, name, attributes json, source_sha). Optional `embedding vector` for semantic resolution.
- `model_edges` (project_id, src_node, dst_node, kind: calls|implements|reads|writes|covers|observed_in, confidence).
- `test_cases` (project_id, type: smoke|happy|negative|edge|e2e|journey|profile, layer: api|ui|integration, target_node, preconditions json, steps json, expected json, **oracle_source: rule-derived|characterization|spec-grounded**, **authored_by: ai|human**, **edited_by_human bool**, **requirement_link nullable**, status, version int, parent_version_id nullable).
- `test_scripts` (project_id, test_case_id, framework: pest|pytest|playwright, code text, generated_by, deterministic bool).
- `runs` (project_id, trigger: manual|ci|change-impact, mode: A|B|C, commit_sha, status, started_at, finished_at).
- `results` (project_id, run_id, test_case_id, outcome: pass|fail|error, triage: real-bug|bad-test|flaky|infra|unknown, evidence_ref).
- `defects` (project_id, result_id, violated_behavior, repro json, status).
- `coverage` (project_id, run_id, dimension: endpoint|page|journey|role-matrix, covered json, gaps json).
- `jobs` (project_id, kind: ingest|generate|run, state, attempts, payload json, idempotency_key, error).

**Versioning rule:** human edits create a new `test_cases` version with `edited_by_human=true`; re-generation produces a sibling version but must not supersede a human-edited head — it diffs and surfaces a merge, never overwrites.

## 4. API surface (REST, `/api/v1`, all project-scoped)

- `POST /projects`, `GET /projects/:id`
- `POST /projects/:id/repos` (connect, read-only), `POST /repos/:id/index`
- `GET /projects/:id/model` (the Brain), `POST /projects/:id/resolve` (NL → nodes)
- `GET/POST/PATCH /projects/:id/test-cases`, `POST /test-cases/:id/lock`
- `POST /projects/:id/plan` (mode A|B|C), `POST /projects/:id/generate`
- `POST /projects/:id/runs`, `GET /runs/:id`, `GET /runs/:id/report`
- `GET /projects/:id/coverage`
- `GET /healthz` (liveness), `GET /readyz` (readiness)

Conventions: cursor pagination, RFC-9457 problem+json errors, idempotency keys on mutating job-creating endpoints, API versioned via path.

## 5. Core interfaces (contracts)

```python
class IngestionAdapter(Protocol):
    def detect(self, repo_path) -> bool: ...
    def extract(self, repo_path) -> NormalizedModel: ...   # endpoints, models, pages, rules

class ExecutionRunner(Protocol):
    framework: str
    def run(self, scripts, target_env) -> list[Result]: ...  # in its own container

class AIProvider(Protocol):
    def generate(self, prompt: str, context: Subgraph, budget_tokens: int) -> str: ...
    def triage(self, failure: FailureEvidence) -> TriageLabel: ...

class BrainResolver(Protocol):
    def resolve(self, nl_query: str, project_id) -> list[ModelNode]: ...   # semantic + structural

class PlannerStrategy(Protocol):   # one per mode
    def plan(self, project_id, prompt: str | None) -> list[TestCaseSpec]: ...
```

First implementations: `LaravelAdapter`, `LaravelRunner` (Pest), `PlaywrightRunner`, `ClaudeCliProvider` (`claude -p`), `PgVectorResolver`, `ModeA/B/CPlanner`.

## 6. AI layer

`ClaudeCliProvider` invokes `claude -p` non-interactively, passing a retrieved subgraph under a hard `budget_tokens` cap (never a repo dump). If a Brain MCP server is configured, it is wired as an MCP tool the provider can call. Model selection is config-driven (frontier for generate, cheap for triage) so production can swap to API/self-host without core changes. All generations record `oracle_source` and `deterministic` flags.

## 7. Brain design

Relational `model_nodes`/`model_edges` + pgvector embeddings on nodes. Resolution = embedding similarity to seed candidates + graph expansion to related nodes. Versioned by `source_sha`; re-index is incremental on changed files. Codebase remains authoritative; the Brain is rebuildable.

## 8. Execution design

Per-stack runner containers carry the target toolchain + the running app + a writable test DB (migrated/seeded). Read-only connection to the real DB is used only for introspection/reference. Evidence (screenshots, Playwright traces, logs, response/DB snapshots) is stored and referenced by `results.evidence_ref`.

## 9. Async / queue design

`jobs` table as the queue (start simple; upgrade to a broker later). States: `queued → running → succeeded | failed | dead`. Rules: at-least-once delivery, **idempotency_key** to dedupe, exponential backoff with jitter on retry, max attempts then dead-letter, graceful cancellation honored at safe points. Long ops (ingest/generate/run) are always jobs, never inline request work.

## 10. Security model (contract)

- Git: fine-grained PAT / deploy key, **read/pull only**, per repo; outputs never pushed by this credential.
- DB: **read-only** role for introspection + reference; **separate writable** ephemeral test DB for execution.
- Tenancy: every query filtered by `project_id`; no cross-project reads.
- Secrets: env-injected, never in code or logs; references stored, not values.
- Least privilege everywhere; input validation at API boundary; authz checks per project.

## 11. Observability

Structured JSON logs with correlation/request IDs and `project_id`; no secrets/PII. Metrics: job throughput/latency, run pass-rate, generation cost/tokens, queue depth. Tracing across API→job→runner. `/healthz` (liveness) and `/readyz` (readiness gating on DB + queue).

## 12. Deployment

Dev: `docker compose up` (db, backend, frontend; runners built on demand). Prod (later): hosted control plane + server-side runners; edge runner for data-residency clients. Migrations run on deploy; forward-only.

## 13. NFRs

- API p95 < 300ms for read/list; job-backed work async with progress.
- Generation context hard-capped; cost tracked per run.
- Horizontal scale by stateless API + job workers; runners scale per project.
- Reliability: no merge on red CI; graceful drain on shutdown; idempotent retries.

## 14. Migration & versioning

Alembic forward-only; destructive changes require an ADR. API versioned by path (`/api/v1`). The data-model contracts (esp. `test_cases` provenance/versioning and `project_id`) are frozen for v1.
