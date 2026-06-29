# Polaris — Active Feature Inventory & Real-Run Runbook

Derived from the actual codebase on branch `docs/feature-inventory` (off `chore/repo-scaffold`
@ `3eb3298`). Every claim carries a `file:line` cite. Two parts:

1. **Active Feature Inventory** — what is actually wired, with status.
2. **Live-Run Runbook** — the exact sequence to run a REAL run against `mumbaisabhaams`
   over the real Claude path (NOT stub), derived from the real files.

### Status labels (used exactly)

| Label | Meaning |
|---|---|
| **ACTIVE** | Wired AND exercised by passing tests / known-working. |
| **WIRED** | Code complete + tested, but never run against a live external dependency (real API key / real login / real target). |
| **PARTIAL** | Some sub-paths work, others stubbed/deferred (the entry says which). |
| **NOT_IMPL** | Placeholder / raises `NotImplementedError` / reserved-but-empty. |

> **Headline honesty:** the *individual* pieces below are heavily tested, but a **full real
> run end-to-end** (ingest `mumbaisabhaams` → generate via real `sonnet` over the bridge →
> execute real Pest) has **never been proven live** — that whole path is **WIRED**. The AI
> providers and the host bridge are tested only against **mock transports / fake runners**.

---

# PART 1 — ACTIVE FEATURE INVENTORY

## Providers (AI layer)

Selection: `ai_provider_mode` (`backend/app/core/config.py:107`, default `claude_cli`), resolvable
**per project** (`project.settings['ai_provider']`) via `backend/app/api/real_execution.py:306` →
factory `backend/app/ai/factory.py:24`.

| Feature | Description | Activation | Evidence | Status |
|---|---|---|---|---|
| Provider factory | Dispatch claude_cli / gemini / stub; unknown → ValueError | `build_ai_provider(settings, mode=)` | `backend/app/ai/factory.py:24-34` | ACTIVE |
| Claude generation (in-process) | `claude -p --output-format json --model <m>` via subprocess CommandRunner | `ai_provider_mode=claude_cli`, no bridge URL | `backend/app/ai/claude_cli.py:95-129` (runner `:92`) | **WIRED** — tested with a *fake* CommandRunner; no automated live `claude` call |
| Claude generation (host bridge) | Same provider; CommandRunner swapped for an HTTP round-trip to the host daemon | `claude_cli` + `claude_bridge_url` set → `make_bridge_runner` injected | factory `backend/app/ai/factory.py:27-39`; client `backend/app/ai/claude_bridge.py:47-99` | **WIRED** — bridge client tested with monkeypatched `urlopen`; never proven to route a live `claude -p` |
| Claude host bridge daemon | Host-side `python3` daemon runs `claude -p` AS the host user; token-guarded, serialized, model allow-list | `make bridge` (`backend/app/bridge/server.py:184`) | server `backend/app/bridge/server.py:61-120,184-202` | **WIRED** — `handle_generate`/`run_claude` unit-tested with a fake runner, "NO real claude and NO network" (`backend/tests/test_claude_bridge.py:6`) |
| **Claude REAL model** | The real-execution stack runs generation as **`sonnet`**, not the config default | runner env `AI_GENERATE_MODEL: ${AI_GENERATE_MODEL:-sonnet}` | compose `infra/docker-compose.real.yml:18`; config default is `claude-opus-4-8` `backend/app/core/config.py:110` | WIRED (real model = `sonnet`) |
| Gemini generation | Google Generative Language API over HTTPS; budget/timeout/retry/usage like Claude | `ai_provider_mode=gemini` (+ `GEMINI_API_KEY`) | `backend/app/ai/gemini.py:280-362`; key refusal `:308-312` | **WIRED** — provider + tests use an **injected mock transport** (`backend/tests/test_gemini.py:68`); **has NEVER made a live Google call** (no key) |
| Gemini per-model rate-limit fallback | Parse 429 body → per-minute (wait+retry, honor RetryInfo) vs per-day (advance model in chain); terminal `AllModelsExhausted` | automatic on the gemini path; `GEMINI_MODEL_CHAIN` | classify `backend/app/ai/gemini.py:102-153`; chain `:316-362`; day-skip `:415` | **ACTIVE in code, MOCK-tested** (`backend/tests/test_gemini_fallback.py`) — but only takes effect on the WIRED Gemini live path |
| Gemini day-exhaustion registry | In-memory per-model day-quota state, next-UTC-midnight reset (no DB) | internal to gemini provider | `backend/app/ai/gemini.py:175-205` | ACTIVE (mock-tested) |
| **Gemini triage** | — | — | `backend/app/ai/gemini.py:430-431` `raise NotImplementedError("triage lands in Sprint 7")` | **NOT_IMPL** |
| **Claude triage** | — | — | `backend/app/ai/claude_cli.py:147-148` `raise NotImplementedError("triage lands in Sprint 7")` | **NOT_IMPL** |
| Stub provider | Deterministic fake generation, no network | `ai_provider_mode=stub` (tests) | `backend/app/ai/stub.py:21` | ACTIVE |
| Budget / retry / usage | Token-budget assembly, bounded backoff+jitter, usage capture (ADR-0049) | shared by all providers | `backend/app/ai/budget.py`, `backend/app/ai/retry.py:21`, `backend/app/ai/usage.py` | ACTIVE |

**AI flags** (`backend/app/core/config.py`): `ai_provider_mode:107`, `ai_generate_model:110`,
`ai_triage_model:111`, `claude_cli_path:112`, `claude_bridge_url:120`, `claude_bridge_token:121`,
`ai_max_budget_tokens:124`, `ai_budget_strategy:125`, `ai_timeout_seconds:127`, `ai_max_attempts:128`,
`ai_retry_base_delay_seconds:129`, `ai_retry_max_delay_seconds:130`, `gemini_api_key:137`,
`gemini_generate_model:138`, `gemini_base_url:139`, `gemini_model_chain:147`,
`gemini_max_minute_retries:149`, `gemini_minute_retry_cap_seconds:152`.

## Ingestion — building the Brain

Selection: `ingestor_mode` (`backend/app/core/config.py:80`, default `stub`; real = `laravel`).

| Feature | Description | Activation | Evidence | Status |
|---|---|---|---|---|
| Laravel whole-repo ingestion | Static-source Brain build (routes→endpoints, models→tables, relations, validation) — no app boot | `ingestor_mode=laravel` → `POST /api/v1/projects/{id}/ingest` | `backend/app/ingestion/laravel/ingester.py:147-334` | ACTIVE |
| Static route parser | Parse `routes/*.php` deterministically | within laravel ingest | `backend/app/ingestion/laravel/static_routes.py` | ACTIVE |
| Static graph parser | Regex/AST over models, migrations, controllers | within laravel ingest | `backend/app/ingestion/laravel/static_graph.py` | ACTIVE |
| Node creation (ENDPOINT/MODEL/TABLE/ROLE) | Idempotent upsert with content_sha (ADR-0010) | within laravel ingest | `backend/app/ingestion/laravel/ingester.py:168-241` | ACTIVE |
| Edge creation (READS/WRITES/CALLS/NAVIGATES) | Confidence-tagged relations | within laravel ingest | `backend/app/ingestion/laravel/ingester.py:243-287` | ACTIVE |
| Artisan route enrichment | Optional merge of dynamic/package routes via `artisan route:list` | `enrich_with_artisan` (default **False**) | `backend/app/ingestion/laravel/ingester.py:116-145` | **PARTIAL** — off by default, boots the app, no production test |
| Endpoint spec extraction | Per-endpoint normalized spec for generation (T1.4) | injectable extractor | `backend/app/ingestion/laravel/extractor.py:34-100` | WIRED — used by generation, not by whole-repo ingest |
| **Clone-at-ingest (git remote)** | `checkout → ingest → cleanup` chain | `ingest_from_git(...)` | `backend/app/ingestion/git_ingest.py:19-37` | **WIRED, NOT CONNECTED** — composition reads `repo_url` as a **local path** (`backend/app/api/real_execution.py:235-242`); you must check the repo out yourself |

## Embeddings & Retrieval (Brain)

| Feature | Description | Activation | Evidence | Status |
|---|---|---|---|---|
| Local fastembed (ONNX) | `BAAI/bge-small-en-v1.5`, 384-dim, lazy-loaded | `embedding_provider=local` (default) | `backend/app/embeddings/fastembed_provider.py:14-42` | ACTIVE |
| Stub embeddings | Deterministic SHA-256 pseudo-vectors, no download | `embedding_provider=stub` | `backend/app/embeddings/stub.py:17-36` | ACTIVE |
| Vector attachment | `model_nodes.embedding` pgvector, HNSW-indexed | on ingest/crawl | `backend/app/models/model_node.py:55-57` | ACTIVE |
| BrainResolver | Hybrid NL→nodes (vector + lexical blend), lexical fallback | `resolve(project_id, query, k)` | `backend/app/brain/resolver.py:67-116` | ACTIVE |
| Lexical fallback | Token overlap + exact name/URI bonus, no model needed | within resolver | `backend/app/brain/lexical.py:27` | ACTIVE |
| CrossLayerResolver — journey | BFS page→endpoint→model→table, depth+500-node cap | `journey(project, node, max_depth)` | `backend/app/brain/cross_layer.py:190-227` | ACTIVE |
| CrossLayerResolver — impact | 1-hop blast (callers, written tables, roles) | `impact(project, node)` | `backend/app/brain/cross_layer.py:235` | ACTIVE |
| EndpointIndex | Match observed URL → endpoint node (template aware) | within crawl/cross-layer | `backend/app/brain/cross_layer.py:97-129` | ACTIVE |

## Generation

| Feature | Description | Activation | Evidence | Status |
|---|---|---|---|---|
| Backend TestGenerator | Endpoint → deterministic plan (no AI) + AI-rendered Pest/PHPUnit; merge-safe persist | within Mode A/B | `backend/app/generation/generator.py:96-144` | ACTIVE (render uses the WIRED provider) |
| E2E generator | Page → cross-layer plan + AI-rendered Playwright spec; mutation gate | within Mode B/C | `backend/app/generation/e2e_generator.py:76-98` | ACTIVE (render uses the WIRED provider) |
| Deterministic plans | `plan_cases` / `build_e2e_plan` — fully deterministic, rule/characterization oracles | within generators | `backend/app/generation/plan.py`, `backend/app/generation/e2e_plan.py:86` | ACTIVE |
| Mutation gate | Reject tautological oracles before write | within generators | `backend/app/generation/mutation_gate.py` | ACTIVE |
| Authored-case rendering | Deterministic-first PHPUnit template, complexity-gated AI fallback | Mode A | `backend/app/generation/authored.py:120-131` | ACTIVE |
| PHPUnit-compatible emit | Classes run under both Pest AND PHPUnit | emitted scripts | `backend/app/generation/generator.py:89` | ACTIVE |

## Execution

Selection: `executor_mode` (`backend/app/core/config.py:79`, default `stub`; real = `orchestrator`).

| Feature | Description | Activation | Evidence | Status |
|---|---|---|---|---|
| Pest/PHPUnit runner detection | Detect target test binary (Pest preferred, else PHPUnit), clear error if neither | within real run | `backend/app/execution/php_test_runner.py:44-59` | ACTIVE |
| JUnit parse + resilience | Parse `--log-junit`; missing/empty/malformed → ERRORED result (run continues, never crashes) | within real run | `backend/app/execution/junit.py:46`; defensive `backend/app/execution/php_test_runner.py:243-261` | ACTIVE |
| Result mapping | Map testcases → scripts; unmatched → ERROR + runner diagnostic | within real run | `backend/app/execution/php_test_runner.py:109-173` | ACTIVE |
| Run lifecycle | Durable run row, per-test results, PASSED/FAILED/ERRORED, always-teardown | within real run | `backend/app/execution/lifecycle.py:32-39,63-215` | ACTIVE |
| Dual-DB safety guard | Refuse anything but a writable, ephemeral test DB | every run | `backend/app/execution/dual_db.py:14-28` | ACTIVE |
| Stub executor | Fabricates one demo finding (clone→up walkthrough) | `executor_mode=stub` (default) | `backend/app/api/composition.py:86-100` | ACTIVE |
| **Orchestrator executor (real)** | Real runner + provider + resolver; runs real Pest as subprocesses (ADR-0036) | `executor_mode=orchestrator` (real stack) | `backend/app/api/composition.py:248-293`; `backend/app/__main__.py:76-82` | **WIRED** — composed only in the real stack; not proven against a live target |

## DB-State (disposable-DB, ADR-0043)

Per-project setting `projects.db_state_tier` (default **`off`**, `backend/app/models/project.py:54-56`).

| Feature | Description | Activation | Evidence | Status |
|---|---|---|---|---|
| Tier: OFF (default) | No DB-state assertions, no provisioning | default | `backend/app/db_state/tiers.py:35`; early-return `backend/app/db_state/run_phase.py:214-215` | ACTIVE (default) |
| Tier: READ_ONLY | SELECT-only table assertions | `db_state_tier=read_only` | `backend/app/db_state/tiers.py:24-26` | ACTIVE (tested) |
| Tier: FULL | Reads + writes to a disposable DB | `db_state_tier=full` | `backend/app/db_state/tiers.py:29-31` | ACTIVE (tested) |
| Non-prod safety gate | Refuse unless explicitly disposable + non-prod | every read/write | `backend/app/db_state/gate.py:66-94` | ACTIVE |
| Table-state oracles | ROW_PRESENT/ABSENT, COLUMN_EQUALS, SOFT_DELETED | tier-gated | `backend/app/db_state/oracle.py:40-135` | ACTIVE (tested) |
| Disposable DB provisioning | Fresh Postgres from migrations, reset/drop between runs | orchestrator + full tier | `backend/app/db_state/provision.py:29-103` | **WIRED** — heavy lane only (`make test-db-state`), not in a real run |

> **Real-run note:** the default tier is `off`, so a `mumbaisabhaams` run does **no** DB-state
> assertions. The target app's own Pest test DB still applies — see runbook step 5.

## Reporting & Findings

| Feature | Description | Activation | Evidence | Status |
|---|---|---|---|---|
| FindingAssembler | Results → root-cause-grouped Findings (errored vs failure label) | Mode B | `backend/app/reporting/finding_assembler.py:169`; wired `backend/app/modes/mode_b.py:250` | ACTIVE |
| Root-cause grouping | Dedup by deepest node + failure signature | within assemble | `backend/app/reporting/finding_assembler.py:118-126` | ACTIVE |
| Oracle-source confidence | Strongest tier wins; flag mixed | within assemble | `backend/app/reporting/finding_assembler.py:129-132,244-246` | ACTIVE |
| Severity scorer | blast radius × outcome/oracle → critical/major/minor | Mode B | `backend/app/reporting/scoring.py:136`; wired `backend/app/modes/mode_b.py:262` | ACTIVE |
| History classifier | new/known/regression/flaky vs prior runs | Mode B | `backend/app/reporting/history.py:87`; wired `backend/app/modes/mode_b.py:264` | ACTIVE |
| Heal reconciliation | Mask a finding when an active heal supersedes it | findings read | `backend/app/reporting/heal_reconciliation.py:35-75` | ACTIVE |

## Healing

| Feature | Description | Activation | Evidence | Status |
|---|---|---|---|---|
| Failure classifier | Model-free LOCATION vs ASSERTION split | within heal scan | `backend/app/healing/classify.py:100-136` | ACTIVE |
| Route re-resolution | Re-bind a moved endpoint (route_name / structural) | within heal scan | `backend/app/healing/reresolve.py:54-131` | ACTIVE |
| Apply route heal | Rewrite addressing token, pin assertion lines byte-identical | confirm | `backend/app/healing/apply.py:69-101` | ACTIVE |
| Heal scan / confirm / reject | Propose location heals; surface assertion findings; RBAC-gated apply | `POST .../heal-scan`, `.../confirm`, `.../reject` | `backend/app/healing/service.py:99-241`; API `backend/app/api/heals.py:54-143` | ACTIVE |

## Incidents & Impact

| Feature | Description | Activation | Evidence | Status |
|---|---|---|---|---|
| Incident recorder | Capture an errored phase (gen/exec/provider/job) in a fresh session; never swallows | provider/job seams | `backend/app/incidents/recorder.py:31-61`; phase tag `backend/app/incidents/capture.py:49-59` | ACTIVE |
| Fingerprinting | Stable hash groups identical failures across runs | within record | `backend/app/incidents/fingerprint.py:38-46` | ACTIVE |
| Incident API (operator) | Cross-tenant list/detail | `GET /api/v1/incidents`, `/{id}` | `backend/app/api/incidents.py:45-80` | ACTIVE |
| Impact selector | ChangeSet → seed nodes → 1-hop blast → covering cases; honest `scope_uncertain` widening | Mode B change-impact | `backend/app/impact/selector.py:139-186`; widen `backend/app/modes/mode_b.py:197-204` | ACTIVE |

## Cases & Documents

| Feature | Description | Activation | Evidence | Status |
|---|---|---|---|---|
| Case diff/versioning | Deterministic field-level diff of case versions | merge engine | `backend/app/cases/diff.py:150-219` | ACTIVE |
| Document ingest + embed | Chunk → batched embed → persist (no N+1) | `POST .../documents`, `/upload` | `backend/app/documents/service.py:39-78`; API `backend/app/api/documents.py:57-141` | ACTIVE |
| Spec-vs-code reconciliation | Extract doc route refs, flag endpoints missing from the Brain | on ingest | `backend/app/documents/reconcile.py:59-97` | ACTIVE |

## Crawler (frontend / Playwright)

| Feature | Description | Activation | Evidence | Status |
|---|---|---|---|---|
| Playwright page fetcher | Node `crawl_page.mjs` driver; real browser, network intercept, `storageState` | injected | `backend/app/crawler/playwright_fetcher.py:64-80` | ACTIVE (real browser in `make test-e2e-runner`) |
| Bounded BFS crawl | Caps (pages/depth/time), origin guard; page nodes + NAVIGATES/CALLS edges | `FrontendCrawler.crawl()` | `backend/app/crawler/crawler.py:80-200` | ACTIVE (tested) |
| **Crawler HTTP surface** | — | — | no `/api/v1/...crawl` route exists | **NOT_IMPL** — code complete but **no API/job entry point**; only exercised by tests (not reachable in a normal run) |

## API, Auth & Orgs

API prefix **`/api/v1`**; routers mounted at `backend/app/main.py:56-68`. Tenancy is **multi-org**
(personal org auto-created on signup, `backend/app/services/auth_service.py:75-78`;
`backend/app/models/organization.py`).

| Group | Endpoints (METHOD path) | Evidence | Status |
|---|---|---|---|
| Auth | POST `/auth/signup` `/signin` `/signout` `/password-reset/{request,confirm}` `/change-password`; GET/PATCH `/auth/me` | `backend/app/api/auth.py:60-197` | ACTIVE |
| Orgs & members | POST/GET/DELETE `/orgs[/{id}]`; members `/orgs/{id}/members[...]`; invites `/orgs/{id}/invites`, `/invites/accept` | `backend/app/api/orgs.py:99-298` | ACTIVE |
| Projects | POST/GET/PATCH/DELETE `/projects[/{id}]`; GET/PUT `/projects/{id}/db-state-tier`; POST `/projects/{id}/ingest`; GET `/jobs/{id}` | `backend/app/api/projects.py:76-315` | ACTIVE |
| Runs | POST/GET `/projects/{id}/runs`; GET `/runs/{id}`, `/usage`, `/events`, `/events/stream` (SSE), `/findings`; PATCH `/runs/{id}/findings/{fid}` | `backend/app/api/runs.py:98-464` | ACTIVE |
| Findings | GET `/findings`, `/projects/{id}/findings`, `/findings/{id}`, `/{id}/screenshot`; POST `/findings/triage` | `backend/app/api/findings.py:75-242` | ACTIVE |
| Documents | POST `/projects/{id}/documents[/upload]`; GET/DELETE; GET `/spec-divergences` | `backend/app/api/documents.py:57-197` | ACTIVE |
| Credentials | PUT/GET/DELETE `/projects/{id}/credentials` | `backend/app/api/credentials.py:40-115` | ACTIVE |
| Healing | POST `.../heal-scan`, `.../confirm`, `.../reject`; GET `.../heals` | `backend/app/api/heals.py:54-143` | ACTIVE |
| Operator (cross-tenant) | GET `/ops/queue`, `/ops/jobs`, `/incidents[/{id}]` | `backend/app/api/ops.py:48-86`, `backend/app/api/incidents.py:45-80` | ACTIVE |
| Health | GET `/healthz`, `/readyz` (unversioned) | `backend/app/api/health.py:19-37` | ACTIVE |

| Auth/tenancy feature | Description | Evidence | Status |
|---|---|---|---|
| Email/password + opaque bearer sessions | bcrypt hash, 14-day token, hashed at rest, revoke on signout | `backend/app/services/auth_service.py:45-79`; deps `backend/app/api/deps.py:53-71` | ACTIVE |
| Org RBAC | OWNER/ADMIN/MEMBER roles scope projects/runs/findings | `backend/app/services/org_service.py`; `backend/app/models/organization_member.py` | ACTIVE |
| Org invites | Email-based, single-use, 7-day, hashed | `backend/app/services/org_service.py:62-99` | ACTIVE |
| Auth rate limiting | Per-IP fixed-window (in-memory, single-instance) | `backend/app/api/rate_limit.py`; config `backend/app/core/config.py:53-59` | ACTIVE |

## Jobs, Worker, Progress, Credentials, Git

| Feature | Description | Activation | Evidence | Status |
|---|---|---|---|---|
| Durable job queue | Postgres `jobs`; enqueue/claim (`FOR UPDATE SKIP LOCKED`)/retry+backoff (ADR-0034) | RUN/INGEST enqueues | `backend/app/services/job_queue.py:45-93` | ACTIVE |
| Job worker | `python -m app.worker`: poll → claim → run → record; orphan recovery | `job_worker_enabled` (default False) | `backend/app/worker.py:28-86`; `backend/app/services/job_worker.py:69-97`; flag `backend/app/core/config.py:65` | ACTIVE |
| Decoupled topology | Slim backend enqueues; runner workers execute (ADR-0036) | `executor_mode=orchestrator` | `backend/app/__main__.py:72-82` | WIRED (real stack only) |
| Run progress + SSE | Ordered `(run_id, seq)` events at run seams; live stream + replay; best-effort | every run | `backend/app/progress/emitter.py:37-115`; SSE `backend/app/api/runs.py:358-382` | ACTIVE |
| Target credentials at rest | Fernet encrypt; write-only; decrypt-at-use only; key required (no fallback) | `TARGET_CREDENTIALS_KEY` | `backend/app/credentials/crypto.py:40-58`; API `backend/app/api/credentials.py:40-115` | ACTIVE |
| Git CLI provider (read-only) | Shallow `fetch --depth=1` checkout; token injected, redacted in logs; no push path | `GitCliProvider` | `backend/app/git/cli.py:31-87`; token `backend/app/core/config.py:164-166` | ACTIVE (real git, fixture-tested) — but the git→ingest chain is **not** in composition (see Ingestion) |

### Status breakdown (Part 1)

- **ACTIVE:** 63
- **WIRED:** 9 — Claude generation (in-process + bridge), bridge daemon, Claude real model, Gemini generation, endpoint extractor, clone-at-ingest, orchestrator executor, disposable-DB provisioning, decoupled topology
- **PARTIAL:** 1 — Artisan route enrichment (off by default)
- **NOT_IMPL:** 3 — Gemini triage, Claude triage, Crawler HTTP surface

---

# PART 2 — LIVE-RUN RUNBOOK: `mumbaisabhaams`, REAL path (NOT stub)

> **NEVER target production** (`https://mumbaisabha.org`). Only the QA env
> `https://msqa.unifyams.ai/` (`docs/running-real.md:13`).
>
> This runs the **real Claude path**: `AI_PROVIDER_MODE=claude_cli` routed through the **host
> bridge**, generating with **`sonnet`** (`infra/docker-compose.real.yml:17-18,24`). The
> end-to-end real run is **WIRED, not yet proven** — expect first-run fix-ups.

Every command below traces to `Makefile`, `infra/docker-compose.real.yml`, or
`docs/running-real.md`. Anything the files don't make unambiguous is marked **VERIFY**.

## 1. Prerequisites

```bash
# (a) Host claude is logged in (Max) — the bridge runs claude AS you on the host.
claude --version                 # expect 2.x
printf 'say ok' | claude -p      # should print a reply (proves the host login works)
```
*Why:* the bridge daemon shells out to the host `claude` (`backend/app/bridge/server.py:72`); if the host isn't logged in, every generation fails.

**Env file — which one & well-formed.** The real stack loads the **root `.env`**
(`docker compose --project-directory .` → `Makefile:12`; `make bridge` sources `./.env` →
`Makefile:41`), **not** `backend/.env`. Set the secrets there (`docs/running-real.md:38-45`):
```
CLAUDE_BRIDGE_TOKEN=<secrets.token_urlsafe(32)>   # shared host↔runner
TARGET_CREDENTIALS_KEY=<Fernet.generate_key()>     # only if you store target creds
GIT_TOKEN=<gitea read-only token>                  # for cloning the target
TARGET_REPO_HOST_PATH=./targets/app                # points the runner at the checkout
```
> ⚠️ **Malformed line flagged (not printed):** the current root `.env` has **two variables
> mashed onto one physical line** (a `GIT_TOKEN=...` value with another `KEY=value` appended,
> no newline). That makes `GIT_TOKEN` absorb the second var and the second var never set. Split
> them onto separate lines before running. (Values withheld — it's a live secret.)
> **VERIFY:** the task brief says `backend/.env`; the real wiring uses the **root** `.env`. If
> you intend `backend/.env`, confirm your compose override actually loads it.

**Target repo checked out** (clone-at-ingest is **not** wired — `docs/running-real.md:49-51`,
`backend/app/ingestion/git_ingest.py:19-37` exists but composition reads `repo_url` as a local
path, `backend/app/api/real_execution.py:235-242`):
```bash
git clone "https://oauth2:${GIT_TOKEN}@git.datagrid.co.in/Datagrid/mumbaisabhaams.git" targets/app
cd targets/app && composer install --no-interaction --prefer-dist && cd -
```
*Why:* the runner bind-mounts `${TARGET_REPO_HOST_PATH}:/targets/app`
(`infra/docker-compose.real.yml:39`); Pest needs `vendor/` present.

**Test DB:** Polaris keeps **DB-state tier `off`** by default (`backend/app/db_state/tiers.py:35`),
so Polaris provisions no DB. The **target app's own** Pest test DB still applies
(`phpunit.xml`/`.env.testing`, e.g. sqlite + `RefreshDatabase` — `docs/running-real.md:140-143`).
> **Heads-up:** a generated `RefreshDatabase` test with no test DB configured will now be recorded
> as an **ERRORED** result (not crash the run) thanks to JUnit-parse resilience
> (`backend/app/execution/php_test_runner.py:243-261`) — but it still won't *pass*. Make the target
> runnable against a throwaway test DB if you want green results.

## 2. Start the host bridge daemon (terminal A — keep it running)

```bash
make bridge      # Makefile:40-42
```
*Why:* runs `python3 backend/app/bridge/server.py` holding your host Claude login. Expect:
`claude-bridge listening on 0.0.0.0:8787` (`backend/app/bridge/server.py:191-193`). Requires
`CLAUDE_BRIDGE_TOKEN` set or it exits (`:186-189`). Leave it up for the whole session.

## 3. Bring up the real stack (terminal B)

```bash
make up-real     # Makefile:34-35 — COMPOSE app.yml + real.yml, builds the runner (~5 min first time)
docker compose --project-directory . -f infra/docker-compose.app.yml \
  -f infra/docker-compose.real.yml ps                 # backend/db/web healthy, runner up
docker logs qa-automation-runner-1 | tail             # "worker: started" executor_mode=orchestrator
# Confirm the runner can reach the bridge:
docker exec qa-automation-runner-1 sh -c 'wget -qO- http://host.docker.internal:8787/health'
#   → {"status": "ok"}   (docs/running-real.md:76-80)
```
*Why:* the real override sets `EXECUTOR_MODE=orchestrator`, `INGESTOR_MODE=laravel`,
`AI_PROVIDER_MODE=claude_cli`, `AI_GENERATE_MODEL=sonnet`, `CLAUDE_BRIDGE_URL`, and
`host.docker.internal` (`infra/docker-compose.real.yml:14-32`). Console: `http://localhost:8080`,
API: `http://localhost:8080/api/v1` (`docs/running-real.md:82`).

## 4. Register the project & ingest `mumbaisabhaams`

```bash
API=http://localhost:8080/api/v1
TOKEN=$(curl -s -X POST $API/auth/signup -H 'Content-Type: application/json' \
  -d '{"email":"you@datagrid.co.in","password":"choose-a-strong-one"}' | jq -r .access_token)
AUTH="Authorization: Bearer $TOKEN"

PID=$(curl -s -X POST $API/projects -H "$AUTH" -H 'Content-Type: application/json' -d '{
  "name":"Mumbai Sabha AMS",
  "repo_url":"/targets/app",
  "app_url":"https://msqa.unifyams.ai/",
  "stack":"laravel"
}' | jq -r .id)
echo "project=$PID"

curl -s -X POST $API/projects/$PID/ingest -H "$AUTH" | jq .   # runner claims + builds the Brain
docker logs -f qa-automation-runner-1                          # watch ingest finish
```
*Why:* `repo_url=/targets/app` is the in-container checkout; `stack=laravel` selects the Pest
runner + Laravel ingestor (`docs/running-real.md:95-104`). Ingest enqueues an INGEST job
(`backend/app/api/projects.py:269-297`) the runner drains.

## 5. Trigger a REAL generation+execution run (sonnet via bridge)

```bash
RID=$(curl -s -X POST $API/projects/$PID/runs -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"mode":"mode_b","strategy":"full_sweep","layers":["api"]}' | jq -r .run_id)
echo "run=$RID"
```
*Why:* Mode B autonomous, API layer first (Pest) — `docs/running-real.md:108-111`. Because
`AI_PROVIDER_MODE=claude_cli` + `CLAUDE_BRIDGE_URL` is set, generation routes to the host bridge
and renders with `sonnet` (`backend/app/ai/factory.py:27-39`, `infra/docker-compose.real.yml:18`).
This is the **real provider** path — watch terminal A (the bridge) print activity.

## 6. Watch output / find the run & findings

- **Live UI:** `http://localhost:8080/runs/$RID/live` (`docs/running-real.md:118`)
- **Events (SSE):** `curl -N -H "$AUTH" $API/runs/$RID/events/stream` (or `/events` to replay)
- **Findings:** `curl -H "$AUTH" $API/runs/$RID/findings | jq`
- **Incidents (look here first if no findings):** `curl -H "$AUTH" "$API/incidents?project_id=$PID" | jq`
  — any errored phase (generation/execution/provider) is captured with the reason
  (`docs/running-real.md:123-125`)
- **Runner logs:** `docker logs -f qa-automation-runner-1`

## 7. Teardown

```bash
make down-real            # Makefile:37-38 — stop the real stack (db volume persists)
# terminal A: Ctrl-C to stop `make bridge`
```

---

## OPTIONAL — Run with Gemini instead of Claude

Delta from the Claude path above. **Gemini `triage()` is NOT_IMPL**
(`backend/app/ai/gemini.py:430-431`), so stay on a **generation+execution run** (Mode B as above);
do not rely on any triage-dependent step (triage is unused by any mode today — Sprint 7).

1. Put the key in the **root `.env`** (secret, never committed; placeholder lives in
   `.env.example:48`):
   ```
   GEMINI_API_KEY=<key from Google AI Studio>
   # optional fallback chain (per-day 429 → next model):
   GEMINI_MODEL_CHAIN=gemini-2.5-flash,gemini-2.0-flash
   ```
2. Select Gemini. Cleanest is **per project** (no compose change): set the project's
   `ai_provider=gemini` via the Edit Project UI / `PATCH /api/v1/projects/{id}`
   (`backend/app/api/real_execution.py:306-325` resolves it per project).
3. Re-run step 5 (Mode B). The per-model rate-limit fallback is automatic
   (`backend/app/ai/gemini.py:316-362`).

> **VERIFY (real gaps for the Gemini live path):**
> - `infra/docker-compose.real.yml` does **not** pass `GEMINI_API_KEY` to the `runner` service
>   (the runner env lists no Gemini var — `:14-32`). You must **add `GEMINI_API_KEY` to the
>   runner `environment:`** (and `AI_PROVIDER_MODE=gemini` there, *or* set it per-project) before
>   the runner can call Gemini. Until then the key in `.env` won't reach the runner.
> - Gemini generation has **never made a live Google call** (WIRED) — the first real call is
>   unproven.

---

*Generated read-only from the codebase; the only file created by this task is this document.*
