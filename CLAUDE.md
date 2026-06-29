# CLAUDE.md — working agreement for this repo

Polaris is an autonomous QA platform: it ingests a target codebase, builds a
**Brain** (a graph of `model_nodes` / `model_edges`), generates tests from it,
executes them against a throwaway environment, and assembles **findings**. This file
is the orientation + the rules. Read it before changing code.

## Monorepo layout

- `backend/` — FastAPI + async SQLAlchemy + Postgres/pgvector. The app is `backend/app`.
- `frontend/` — Vite + React + TypeScript + Tailwind (`frontend/src`).
- `infra/` — docker-compose files (`docker-compose.yml` test base, `.app.yml`
  packaged stack, `.real.yml` real-execution overlay, `.test.yml` test services).
- `docs/adr/` — Architecture Decision Records, numbered `ADR-XXXX-*.md`. Non-trivial
  or surprising decisions get an ADR; reference it in code comments.
- `Makefile` — the canonical command surface. Everything runs in Docker.

## Architecture you must respect

- **Decoupled topology (ADR-0036).** The slim **backend** only ENQUEUES work onto a
  durable `jobs` queue (ADR-0034). A **runner** worker drains the queue and executes
  (ingest / run) as subprocesses of its own process. The backend never executes a
  target; the runner never serves HTTP.
- **Dual-DB rule (Architecture §9).** A runner writes ONLY to an ephemeral, throwaway
  test DB; the real/control-plane DB is read-only to it. `app/execution/dual_db.py`
  guards this — never bypass it.
- **Stub-vs-real seams (env modes), default to safe stubs so a clone boots with zero
  credentials:**
  - `EXECUTOR_MODE`: `stub` | `orchestrator`
  - `INGESTOR_MODE`: `stub` | `laravel`
  - `AI_PROVIDER_MODE`: `stub` | `claude_cli` | `gemini`
  - `EMBEDDING_PROVIDER`: `stub` | `local` (fastembed)
- **Ingestion is STATIC source reading (ADR-0055).** It NEVER boots the target app
  (no `artisan`, no DB, no `vendor/`). Routes/models/migrations are parsed from source.
- **Generation emits PHPUnit-compatible test classes** that run under both Pest and
  PHPUnit. The executor detects which binary the target ships.
- **AI layer is pluggable.** `app/ai` — one `AIProvider` interface, provider chosen by
  `AI_PROVIDER_MODE`. Calls go through a shared budget + bounded-retry + usage-capture
  path (ADR-0049). Add a provider by implementing `AIProvider` and wiring the factory.
- **Run-scoped cross-cutting state travels via contextvars**, not threaded params
  (the progress emitter `app/progress`, the AI usage collector `app/ai/usage`).
- **Repositories are project-scoped and idempotent.** Reads/writes are tenant-scoped
  by `project_id`; upserts are idempotent (re-ingest/re-run updates in place). Don't
  write a query that crosses projects.

## The gate — `make test` must exit 0

Run everything in Docker via the Makefile. Do NOT run `pytest`/`npm` on the host.

- `make test` — the gate: backend `pytest` + coverage, frontend `vitest`, e2e
  Playwright. **This must pass before you call work done.**
- `make lint` — `ruff check app && black --check app && mypy app`, plus the frontend
  `eslint` / `prettier` / `tsc`. The mypy + black + ruff gate is on `app` (not `tests`).
- Heavy lanes kept OUT of `make test` (run when relevant): `make test-runners` (real
  PHP/Pest in the Laravel runner image), `make test-embeddings` (real fastembed),
  `make test-e2e-runner` (real browser), `make test-db-state`.
- `make audit` — `pip-audit` (shipped deps) + `npm audit --omit=dev`.

Fast iteration without a rebuild: bind-mount the working tree into the test image,
e.g. `… run --rm -v "$PWD/backend:/host" -w /host backend-tests sh -c "pytest …"`.

## Coding standards

- **Python:** type-annotate everything in `app` (mypy enforces). `ruff` + `black`
  (line length 88). No bare `except` without a `# noqa: BLE001` + a real reason.
  Pure/deterministic core logic where possible (no `Date.now`/random in the seams that
  must be reproducible). Prefer the dedicated repository/service over ad-hoc SQL.
- **TypeScript/React:** functional components, hooks, the existing design-system
  components and API client — match the surrounding code; `eslint`/`prettier`/`tsc` gate.
- **Tests are part of the change, not optional.** Cover the happy path AND the failure
  path. Match the existing test style (fast hermetic suite + injected fakes; real
  toolchains only in the heavy lanes).
- **Comments explain WHY**, at the altitude of the surrounding code. Match its density.
- New surprising behaviour ⇒ an ADR in `docs/adr`, referenced from the code.

## Security (treat this as an industry product)

- **Secrets come from the environment only.** Never hardcode, never commit, never log
  them, never return them in an API payload, never put them in the DB as plaintext.
  `.env` is gitignored; `.env.example` documents knobs with placeholders.
- The only at-rest secret store is the **encrypted credentials vault** (Fernet,
  `TARGET_CREDENTIALS_KEY`, ADR-0053) — write-only, never echoed back.
- API keys (e.g. `GEMINI_API_KEY`, `GIT_TOKEN`) are env-only and pass to upstreams via
  **headers, not URLs** (a key in a URL leaks into logs). Redact on the way out.
- **Validate any client-chosen mode against an allow-list** (provider, status, role) —
  never feed user input into a command, a path, a URL host, or a model/argv element.
- **Never target production.** The runner writes only to a throwaway test DB
  (dual-DB guard). Real runs target the QA environment, not prod.
- Outbound calls are timeout-bounded with bounded retry; auth failures are fatal, not
  retried forever.

## Git / workflow conventions

- Trunk is **`chore/repo-scaffold`**. Branch a feature off freshly-synced trunk:
  `git checkout -b feat/<name> <trunk-sha>`.
- Commit messages: imperative subject, a body explaining the WHY, and end with:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- For delegated/agent tasks: implement, get `make test` to exit 0, **STOP and paste —
  don't merge** unless explicitly told to. Don't commit secrets.

## Where things live (quick map)

- Ingestion: `app/ingestion` (Laravel static parsers in `app/ingestion/laravel`).
- The Brain / resolver: `app/brain`, repositories in `app/repositories`.
- Generation: `app/generation` (plan → render → extract). AI: `app/ai`.
- Execution: `app/execution` (runner, JUnit parsing, lifecycle, dual-DB).
- Orchestration: `app/modes` (mode_b autonomous), the durable worker
  `app/services/job_worker.py`, run wiring `app/api/real_execution.py`.
- Reporting/findings: `app/reporting`. API routes: `app/api`. Config: `app/core/config.py`.
- Per-project target/run config resolution: `app/api/project_target.py` (ADR-0054).
