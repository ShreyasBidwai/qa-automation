# Engineering Standards — QA Automation Platform

*Status: baseline (v1). Binding on all code, human- or agent-written. The maker (Claude Code) must read and follow this; the checker (Claude AI) verifies against it. Companion to `01-architecture.md`, `03-trd.md`.*

---

## 1. Purpose

One reference for how we build, so quality is consistent whether code comes from a person or an agent. If a rule here conflicts with a task prompt, this document wins unless an ADR overrides it.

## 2. Repository & branching

- Monorepo: `/backend /frontend /runners /infra /docs /tests`.
- Trunk-based via GitHub Flow: short-lived branches off `main`, named `type/scope-short-desc` (e.g. `feat/backend-health`, `fix/runner-timeout`).
- `main` is always green and deployable. No direct pushes; PRs only.

## 3. Commits & pull requests

- **Conventional Commits**: `feat: …`, `fix: …`, `chore: …`, `test: …`, `docs: …`, `refactor: …`.
- PRs are small and single-purpose (ideally one task). Each PR: description, linked task, what's tested, what's deferred.
- Required to merge: review approved, full CI green, no unresolved threads, DoD met.

## 4. Code style & quality

- Python: ruff (lint) + black (format) + mypy (types, strict on new modules). Type-hint everything public.
- TS/React: eslint + prettier; strict TS; no `any` without justification.
- Naming: descriptive, no abbreviations; functions do one thing; files cohesive.
- No dead code, no commented-out blocks, no TODOs without an issue reference.

## 5. Project structure conventions

- Backend: app factory pattern; routers thin, logic in services, data in repositories; adapters/runners/AI behind the interfaces in TRD §5.
- Frontend: feature-foldered; design tokens centralized; components presentational vs container; data access via a typed API client.

## 6. Configuration & secrets (12-factor)

- All config via environment (`pydantic-settings`); `.env` for dev, templates committed as `.env.example`.
- **No secrets in code, logs, or VCS.** Store references, inject values at runtime.
- Fail fast at startup if required config is missing.

## 7. Error handling & taxonomy

- Typed, explicit errors; no bare `except`, no silent swallow.
- Distinguish: client errors (4xx, validation), domain errors (expected, handled), infra errors (retryable), bugs (surfaced loudly).
- API returns RFC-9457 problem+json with a stable error code; never leak stack traces or secrets to clients.

## 8. Logging

- Structured JSON; one event per log line; include `request_id`/`correlation_id`, `project_id`, `job_id` where relevant.
- Levels: DEBUG (dev detail), INFO (state transitions), WARN (recoverable), ERROR (needs attention). No PII, no secrets, no full payloads.
- Correlation IDs propagate API → job → runner.

## 9. Observability

- Endpoints: `GET /healthz` (liveness — process up), `GET /readyz` (readiness — DB + queue reachable; gates traffic).
- Metrics: queue depth, job latency/throughput, run pass-rate, generation token cost. Tracing across the request→job→runner path.
- Every long-running operation reports progress.

## 10. Background jobs & queuing

- Long work (ingest, generate, run) is **never** done inline in a request — it's enqueued as a `jobs` row.
- **At-least-once** delivery; every job carries an **idempotency key** so re-delivery is safe (dedupe before side effects).
- **Retries** with exponential backoff + jitter; cap attempts; then **dead-letter** with the error captured.
- Jobs are **idempotent and resumable**; partial progress is checkpointed where feasible.
- Workers pull, mark `running`, heartbeat, and release on completion/failure. Start with the DB-backed queue; swap to a broker later without changing the job contract.

## 11. Graceful startup & shutdown

- **Startup:** validate config → connect dependencies (DB, queue) with bounded retries → run/verify migrations → only then flip `/readyz` to ready.
- **Shutdown:** trap SIGTERM/SIGINT → stop accepting new work (fail `/readyz`) → **drain** in-flight requests and jobs up to a timeout → release connections/locks → exit. Never hard-kill mid-job; re-queue if drain times out.
- Runners: ensure spun-up target apps and test DBs are torn down on completion or failure (no leaks).

## 12. Concurrency & resource limits

- Every external call (git, DB, AI, runner) has a **timeout** and a sensible **retry** policy.
- Bounded connection pools; bounded worker concurrency per project to avoid noisy-neighbor.
- Support **cancellation** (a run/job can be cancelled and cleans up).
- Rate-limit AI calls and external APIs; back off on 429s.

## 13. API design

- REST under `/api/v1`; nouns for resources; project-scoped paths.
- Cursor pagination on lists; consistent filtering/sorting params.
- **Idempotency keys** on mutating endpoints that create jobs.
- Versioned by path; breaking changes bump the version.
- Validate all input at the boundary (Pydantic); reject unknown fields.

## 14. Database

- Alembic migrations only; **forward-only**; destructive changes need an ADR + backfill plan.
- Every table has `project_id` + audit columns; queries are tenancy-filtered — no global reads.
- Index foreign keys and hot query paths; no N+1 in services.
- Migrations run automatically on deploy and are verified at startup.

## 15. Testing standards

- Pyramid: many unit, fewer integration, few E2E. Deterministic only — **zero tolerance for flaky**; quarantine + fix, don't retry-mask.
- Coverage gate on changed code (start ~80% lines on backend services); meaningful assertions, not tautologies.
- Fixtures/factories for data; tests isolated, parallel-safe, no shared mutable state.
- The platform **tests itself every sprint**; mutation testing added later as an oracle-quality gate.

## 16. CI/CD

- **CI is deferred for now.** The GitHub Actions workflow is preserved (disabled) at `docs/ci/ci.yml.disabled` and is re-enabled by moving it back to `.github/workflows/ci.yml`. It runs the full pipeline **inside Docker** — build → lint → typecheck → unit → integration → (E2E where relevant) — mirroring local `docker compose`, fail-fast, with coverage/test-report artifacts.
- **Until CI is re-enabled, the per-task gate is local:** `make test` (and `make lint`) must be green in Docker before a task is considered done (§20). These are the same Docker targets the workflow runs, so there is no drift when CI returns.
- Pre-commit hooks (ruff/black/eslint/prettier) still run locally on every commit (`pre-commit install`).
- When re-enabled: CI mirrors local `docker compose` so "works on my machine" can't happen; fail-fast; **no merge on red**; artifacts published.

## 17. Docker conventions

- Multi-stage builds; pinned base images and dependency versions; `.dockerignore` to keep contexts small.
- Containers run as **non-root**; minimal images; one concern per service.
- Healthchecks on every service; `depends_on` with condition checks.
- `docker compose up` is the canonical dev entrypoint; a `Makefile` wraps common commands (`up`, `down`, `test`, `lint`, `migrate`).

## 18. Security baseline

- Least privilege everywhere (git read-only, DB read-only + separate test DB, scoped tokens).
- Dependency scanning in CI; pin and patch.
- Validate/escape all external input; parameterized queries only.
- Authz checked per project on every request; no cross-tenant access.
- Secrets via env/secret store; rotate; never log.

## 19. Documentation & ADRs

- Public functions/modules documented; READMEs per package explain how to run/test.
- Architecture decisions recorded as numbered ADRs in `/docs/adr` (context → decision → consequences). Contracts change only via ADR.

## 20. Definition of Done (every task)

Code merged via reviewed PR · works in `docker compose up` · tests added and **`make test` green locally** (full CI once re-enabled, §16) · no secrets · logging/health where relevant · graceful start/stop honored for services · docs/ADR updated if a contract changed · tracker note added.

## 21. Maker–Checker workflow

- **Maker** (Claude Code, fresh session per task): read the referenced docs, implement the task, satisfy acceptance criteria, leave CI green.
- **Checker** (Claude AI, separate session): without trusting the maker, verify against the acceptance criteria and this document — run/inspect, look for missing tests, silent failures, secret leakage, non-idempotent jobs, missing timeouts/graceful-shutdown, tenancy gaps. Report PASS/FAIL with specifics.
- A task is accepted only when the checker passes it. Disagreements are resolved by re-running the maker with the checker's findings.
