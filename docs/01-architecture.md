# Architecture — QA Automation Platform

*Status: baseline (v1). Companion to `02-prd.md`, `03-trd.md`, `04-engineering-standards.md`. Changes to anything marked a "contract" require an ADR in `/docs/adr`.*

---

## 1. Purpose & goals

A platform that understands a target web application (backend + frontend) and autonomously generates, executes, and reports tests across all types — smoke, happy-flow, negative, edge, E2E, user-journey, role/profile. It operates in three modes over one engine, is run by QA engineers who can edit any test case at any time, and treats its accumulated understanding of each system as a compounding asset.

Design goals: stack-agnostic core; deterministic where possible, AI only at the edges; portable test output (no lock-in); trustworthy oracles (assert correctness, not just current behavior); knowledge that compounds per commit.

## 2. Architectural principles

1. **Stack-agnostic core + thin adapters.** The core (model, planner, generation orchestration, evaluator, reporter) never changes per stack. Only ingestion and execution adapters are stack-specific.
2. **Deterministic-first.** Prefer rule-based extraction, schema/template/record generation, and deterministic execution. Use the AI layer only for the intent→code gap and oracle synthesis.
3. **Codebase is ground truth.** The Brain is a derived, possibly-stale index that accelerates retrieval. Generation always reads actual code before asserting.
4. **Knowledge compounds.** The system model is persistent, versioned per commit, and updated by run evidence (the feedback loop).
5. **Portability.** Emit standard test code (Pest/pytest/Playwright) committable to the target repo.
6. **Tenancy first.** Every entity is scoped by `project_id` from the first migration.

## 3. System context

```
        ┌───────────────┐     read-only pull      ┌────────────┐
        │  Target repo  │◄────────────────────────│            │
        └───────────────┘                         │            │
        ┌───────────────┐   read-only introspect  │            │
        │ Target DB     │◄────────────────────────│  QA        │
        └───────────────┘                         │  Platform  │
        ┌───────────────┐   run app + tests        │  (control  │
        │ Running target│◄────────────────────────│   plane)   │
        └───────────────┘                         │            │
        ┌───────────────┐   optional MCP tool      │            │
        │ Brain MCP srv │◄────────────────────────│            │
        └───────────────┘                         │            │
        ┌───────────────┐   generate (claude -p)   │            │
        │ AI provider   │◄────────────────────────│            │
        └───────────────┘                         └─────┬──────┘
                                                         │ browser
                                                   ┌─────▼──────┐
                                                   │ QA engineer│
                                                   └────────────┘
```

## 4. Logical architecture — layers

```
INGESTION    → git (read-only), DB schema (read-only), running app, requirements (optional)
UNDERSTANDING→ Code model + Architecture model + Requirements model + Runtime model
SYSTEM MODEL → "the Brain": Postgres (relational) + pgvector (semantic), versioned per commit
PLANNING     → rule-based planner + AI assist; THIS is where the three modes differ
GENERATION   → deterministic (template/schema/record) first, AI fallback; portable output
EXECUTION    → runners per target stack; dual-DB; evidence capture
EVALUATION   → oracle compare + triage (bug / bad-test / flaky)
REPORTING    → results, coverage & gaps, CI output; writes evidence back to the Brain (feedback loop)
```

**The three modes are a single switch on the planning layer:**
- **Mode A** — human populates the test plan; generation + execution + reporting are identical downstream.
- **Mode C** (default) — AI proposes the plan from the Brain; QA steers via NL prompts; AI owns completeness.
- **Mode B** — AI populates and runs the plan autonomously, no human input.

## 5. Components & responsibilities

| Component | Responsibility |
|---|---|
| Ingestion adapters | Stack-specific extraction (routes, models, schema, pages) → normalized model |
| Brain (system model) | Persistent graph of endpoints/pages/models/tables/roles + embeddings; NL→target resolution |
| Brain MCP connector | If a Brain MCP server is configured, expose it to the AI layer as a tool; else use local index |
| Planner | Walks the Brain, produces a test plan per type; mode switch lives here |
| AI layer | Pluggable `generate()`/`triage()`; `claude -p` impl for dev; context-budgeted |
| Generators | Turn plan items into portable test code; deterministic-first |
| Execution runners | Stack-specific containers that run the generated tests against the running target + test DB |
| Evaluator/Triager | Compare to oracle; classify outcomes |
| Reporter | Reports, coverage/gap, CI output; persists evidence to the Brain |
| Job queue | Async orchestration of ingest/generate/run; retries, idempotency |
| API + UI | FastAPI control plane; React operator console |

## 6. Data flow (Mode C, the default)

1. QA prompts: "test that the loyalty discount applies correctly."
2. Brain resolves the phrase → relevant endpoints/pages/code (semantic + structural).
3. Planner expands into concrete test cases (happy + negative + edge), tagging each with `oracle_source`; emits a weak-oracle warning if no spec grounds "correctly."
4. Generator produces portable test code, grounded in the resolved subgraph (not the whole repo).
5. Runner executes against the running target + writable test DB; captures evidence.
6. Evaluator compares to oracle; triager classifies failures.
7. Reporter writes the report + coverage/gaps and pushes confirmed edges/coverage back to the Brain.

Mode A skips step 1–3's AI proposal (human authors the cases). Mode B runs 1–7 with no human in the loop.

## 7. The Brain (system model)

- **Now (lightweight):** relational tables for endpoints/pages/models/tables/roles + their edges, plus pgvector embeddings for NL resolution. Versioned by target commit SHA.
- **Later (full):** richer graph (optionally Apache AGE), runtime-trace edges, requirement nodes, cross-layer links.
- **MCP:** optional accelerator; codebase remains ground truth.

## 8. AI layer

A single interface (`AIProvider`) with `generate()` and `triage()`. The dev implementation shells to `claude -p`; production swaps to API or self-hosted open weights with no core change. Context is always a retrieved subgraph under a hard token budget — never a repo dump. Model tiering: frontier for generation/oracle, cheap for triage/parsing.

## 9. Execution model

- **Runners** are per-target-stack Docker images (`runners/laravel`, `runners/playwright`, `runners/python`) carrying the target's toolchain plus the running app and a writable test DB.
- **Dual-DB rule:** read-only connection to the real DB for introspection/reference; a separate writable, ephemeral test DB for execution. Never write to the read-only DB.
- **Async:** ingest/generate/run are queued jobs (see TRD §9 and Standards §10) with retries, idempotency, and graceful cancellation.

## 10. Deployment topology

- **Now:** hosted control plane (FastAPI + React + Postgres/pgvector) accessed via browser; runners execute server-side. Single internal deployment for customer-zero dogfooding on Datagrid client work.
- **Later:** control plane + **edge runner** — the part touching sensitive client code/DB and executing tests runs in the client's network; the Brain/results/UI stay central. Add only when a client's data residency requires it.
- **Multi-project:** one deployment serves many projects; isolation by `project_id` throughout.

## 11. Cross-cutting

Security, observability, queuing, graceful start/stop, and config are governed by `04-engineering-standards.md`. Key points: git/DB access is least-privilege read-only; secrets via env; structured logging with correlation IDs; health/readiness/liveness endpoints; job retries with backoff and dead-lettering; signal-driven graceful drain.

## 12. Tech stack

Backend FastAPI (Python 3.12), SQLAlchemy + Alembic, pytest. Frontend React + Vite + TS, Tailwind + shadcn/ui + Radix, TanStack Table, Recharts, Vitest + Playwright. Data Postgres 16 + pgvector. Infra Docker + Compose, GitHub Actions. AI: pluggable, `claude -p` for dev.

## 13. Key decisions (ADR summary)

- ADR-001 Monorepo. ADR-002 Stack-agnostic core + adapters. ADR-003 Deterministic-first generation. ADR-004 Codebase as ground truth, Brain as accelerator. ADR-005 `project_id` tenancy from migration #1. ADR-006 Dual-DB execution. ADR-007 Pluggable AI layer. ADR-008 Hosted control plane now, edge runner later.
