# QA Automation Platform — Project Plan & Sprint Tracker

*Single source of truth for execution. Detailed for what you build now (setup + walking skeleton), roadmap-level further out. Update the tracker table as you go. Every sprint ships in Docker and ends green in CI — no exceptions.*

---

## 1. What we're building

An autonomous, full-stack QA platform that understands a target web app (backend + frontend), then generates, executes, and reports tests across types — smoke, happy-flow, negative, edge, E2E, user-journey, and role/profile. Three operating modes share one engine: **Mode A** (QA authors cases, tool scripts them), **Mode C** (hybrid — AI proposes cases and the QA can prompt in natural language; the default), and **Mode B** (fully autonomous). QAs operate the tool and can edit any test case at any time. The platform's own stack is **Postgres + pgvector, FastAPI, React**; the apps it tests can be any stack (Laravel/Python/React/…), reached through thin adapters. Dependencies per the design: a running target app + read-only access is the floor; codebase + a lightweight "Brain" index make Mode C work; business docs make oracles trustworthy. Codebase is always the ultimate ground truth; a Brain MCP server, if present, is an optional accelerator.

**First testbed (customer zero):** AAHOA (Laravel). You own it, it's a real codebase, and the Brain already exists.

## 2. Tech stack & repository structure

- **Backend:** FastAPI (Python 3.12), SQLAlchemy + Alembic migrations, pytest.
- **Frontend:** React + Vite + TypeScript, Tailwind + shadcn/ui + Radix, TanStack Table, Recharts, Vitest + Playwright.
- **Data:** Postgres 16 + pgvector.
- **AI layer:** pluggable model interface; `claude -p` (Claude Code) for dev/pre-prod; API/self-host swappable later.
- **Infra:** Docker + Docker Compose from day one; GitHub Actions CI.
- **Repo:** monorepo.

```
/qa-platform
  /backend        FastAPI app, adapters, AI layer, alembic
  /frontend       React + Vite app, design system
  /runners        target-stack execution images (php/laravel, node/playwright, python)
  /infra          docker-compose.yml, CI configs, env templates
  /docs           this plan, schemas, ADRs
  /tests          backend + frontend test suites (the tool tests itself)
```

## 3. Engineering conventions (non-negotiable)

1. **Docker from day one.** `docker compose up` brings the entire stack live on any machine. No "works on my laptop."
2. **Every sprint runs tests.** Each sprint adds to the tool's own test suite; CI runs the full suite in Docker on every push. A sprint is not "done" if CI is red.
3. **Definition of Done is universal** (see §5) and applies to every sprint on top of its specific acceptance criteria.
4. **Tasks are Claude-Code-sized.** Each task is a discrete, verifiable unit with its own acceptance check, so it can be handed to a single focused agent session and confirmed by a test.
5. **Contracts before features.** The three load-bearing contracts — the test-case schema, the deployment topology, and the design tokens — are fixed early (Sprints 0–1) and changed only via an ADR in `/docs`.

## 4. Sprint tracker

*Update Status (`Not started` / `In progress` / `Done` / `Blocked`) and Tests (`—` / `Green` / `Red`) as you go.*

| # | Sprint | Goal | Effort | Status | Tests | Notes |
|---|--------|------|--------|--------|-------|-------|
| 0 | Foundation & setup | Whole stack runs in Docker, CI green, design tokens in | M | Not started | — | |
| 1 | Walking skeleton | One Laravel endpoint → generated + run + reported tests | M | Not started | — | The thesis gate |
| 2 | Ingestion + lightweight Brain | Read-only git + Laravel extraction + pgvector resolution | L | Not started | — | |
| 3 | Editable, versioned test cases | Mode A core; human edits never clobbered | M | In progress | Green | Lineage + edit service (T3.1): edits append an immutable, current version (full provenance, human-edited flag); one-current via partial unique index; current/history/version queries; AI v1 preserved on edit (migration 0007). Re-gen merge engine (T3.2): generation persists through CaseMergeService keyed by deterministic case_key — fresh→create, AI-only→update-in-place, human-edited→non-current pending proposal (current never clobbered); migration 0008 forward-only. Deferred: proposal resolution (accept/reject, T3.3), CRUD API endpoints, stale-marking. |
| 4 | Frontend E2E + cross-layer | Playwright journeys linked to backend endpoints | L | Not started | — | |
| 5 | Mode C (hybrid) + NL prompting | "Test the loyalty discount" → cases + scripts + run | L | Not started | — | Default mode |
| 6 | Professional UI | App shell + core screens, light design system | L | Not started | — | Design mockups optional |
| 7 | Evaluate / triage / reporting | Bug vs bad-test vs flaky; coverage & gap report | M | Not started | — | |
| 8 | Mode B + change-impact + feedback | Autonomous run; PR blast-radius; Brain updates | L | Not started | — | |
| 9+ | Feature-full backlog | Oracle upgrades, self-host, edge-runner, multi-stack | — | Not started | — | See §6.10 |

## 5. Universal Definition of Done (every sprint)

- Code merged to `main` via PR with review.
- The sprint's feature works end to end inside `docker compose up`.
- New tests added for the sprint's logic; **full CI suite green in Docker**.
- No secrets in code; config via `.env` (templates in `/infra`).
- Any contract change recorded as an ADR in `/docs`.
- Short demo note in the tracker: what works, what's deferred.

---

## 6. Sprints

### Sprint 0 — Foundation & setup *(installation only)*

**Goal:** Anyone can clone the repo, run `docker compose up`, and get a live, tested, lint-clean stack with the design system in place. No product features yet.

**Tasks:**
1. Initialize monorepo with the structure in §2; add README, `.gitignore`, license.
2. `docker-compose.yml` with three services: `db` (Postgres 16 + pgvector), `backend` (FastAPI/uvicorn), `frontend` (Vite dev server). Healthchecks + `depends_on`.
3. Backend skeleton: FastAPI app, `/health` endpoint, SQLAlchemy + Alembic wired, a no-op initial migration, settings via env.
4. Frontend skeleton: Vite + React + TS + Tailwind + shadcn/ui; a single page that calls `/health` and renders status.
5. **Design tokens** (see §6.6 palette): zinc neutrals, `#FAFAFA` base, semantic status colors (pass/fail/flaky/info), one indigo accent; encoded as Tailwind theme + CSS variables. Light mode only for now.
6. Test harness: pytest (backend) with one passing test; Vitest (frontend) with one passing test; a Playwright smoke test hitting the running frontend.
7. CI: GitHub Actions — build images, run lint (ruff + eslint), run all tests *inside Docker*, fail on red.
8. Pre-commit hooks (ruff, black, eslint, prettier).

**Tests this sprint:** `/health` returns 200; frontend renders backend status; one trivial unit test per side; CI runs the whole thing in Docker.

**DoD:** `docker compose up` → frontend shows backend+DB healthy; CI green; design tokens visibly applied.

---

### Sprint 1 — Walking skeleton (the thesis gate)

**Goal:** For **one** AAHOA endpoint, run the full loop manually-orchestrated: extract → generate → execute → report. This sprint exists to answer the riskiest question: *are the generated tests good enough to keep?*

**Tasks:**
1. **Test-case schema** (the contract): fields incl. `id`, `type`, `layer`, `target` (endpoint/page), `preconditions`, `steps`, `expected`/oracle, `oracle_source` (`rule-derived` / `characterization` / `spec-grounded`), `authored_by` (`ai`/`human`), `edited_by_human` (bool), `requirement_link` (nullable), version lineage. Persist in Postgres.
2. **AI layer wrapper:** a pluggable `generate(prompt, context) -> code` interface; first implementation shells to `claude -p`. Context is passed in; no whole-repo dumping.
3. **Deterministic extraction (Laravel-concrete, no abstraction):** parse one endpoint's route + controller + validation rules.
4. **Generation:** produce a happy-path test + rule-derived negative tests (missing required field, unauthorized, not-found) as Pest code, grounded in the extracted rules.
5. **Execution runner:** a `runners/laravel` Docker image with PHP + Composer + the AAHOA app + a throwaway test DB (Postgres or sqlite, migrated + seeded). Run the generated Pest tests here. *(Note: executing target tests means standing up the target app in Docker — budget for this.)*
6. **Report:** a 10-line summary — endpoint covered, tests generated, pass/fail, gaps.
7. **The gate experiment:** seed a deliberate bug (mutant) in the endpoint; confirm a generated test fails. Manually review: "would a senior dev keep these tests?"

**Tests this sprint:** schema CRUD tests; extraction correctness on the chosen endpoint; the mutant-kill check; the tool's own unit tests stay green in CI.

**DoD:** the loop produces kept-quality tests for one endpoint; the gate (compile + run + mutant-kill + keep-worthy) passes and is documented. **If the gate fails, stop and fix generation before Sprint 2 — this is the whole point.**

---

### Sprint 2 — Ingestion adapters + lightweight Brain

**Goal:** Automate what was manual in Sprint 1, across a whole repo, and add semantic resolution.

**Tasks:**
1. Read-only git integration (clone/pull) via fine-grained PAT/deploy key; never write.
2. Laravel ingestion adapter: extract all routes, controllers, validation rules, Eloquent models → migrations → tables, into the normalized model.
3. Store the model in Postgres as the lightweight Brain (nodes: endpoint, page, model, table, role).
4. Embeddings + pgvector: index code/symbols for NL → target resolution.
5. Brain MCP detection: if a Brain MCP server is configured, wire it to the AI layer as a tool; else use the local index. Codebase remains ground truth.
6. Read-only DB connection for schema introspection + reference data (separate from the writable test DB used for execution).

**Tests this sprint:** extraction accuracy across AAHOA; NL-resolution precision on a fixed query set; git read-only enforced (write attempts fail by design).

**DoD:** point the tool at AAHOA, get the full system model + working "find the code for X" resolution.

---

### Sprint 3 — Editable, versioned test cases (Mode A core)

**Goal:** Make test cases first-class, human-editable entities — the "QAs can edit anytime" requirement.

**Tasks:**
1. Test-case CRUD API + versioning + provenance (build on the Sprint 1 schema).
2. **Re-generation merge logic:** human-edited cases are locked or diff-merged on re-gen, never overwritten.
3. Mode A deterministic-first script generation: schema/template paths where input is structured; AI fallback only for free-form intent and assertions.
4. Import path for QA-authored cases (structured format + NL).

**Tests this sprint:** edit-then-regenerate never clobbers; version lineage correct; deterministic vs AI routing picks the right path per input.

**DoD:** a QA can author, edit, and re-run cases; their edits survive re-generation.

---

### Sprint 4 — Frontend E2E + cross-layer linking

**Goal:** The frontend half of testing, linked to the backend.

**Tasks:**
1. `runners/playwright` image; Playwright execution wired in.
2. Frontend route/page discovery (router config or crawl of the running app).
3. Generate UI journeys; **locator stability ranking** (ARIA role → label → text → CSS, no brittle XPath).
4. Evidence capture: screenshots, traces, network logs.
5. Cross-layer link: record which backend endpoints a journey hits; store edges in the Brain.

**Tests this sprint:** generated journeys run headless and pass on a known-good build; cross-layer links resolve correctly.

**DoD:** a UI journey runs end to end and a backend-caused failure is attributed to the backend, not logged as flaky.

---

### Sprint 5 — Mode C (hybrid) + NL prompting *(the default mode)*

**Goal:** AI proposes coverage and the QA steers with natural language.

**Tasks:**
1. Rule-based planner that walks the Brain and proposes cases per test type.
2. NL prompt path: "test that the loyalty discount applies correctly" → resolve via Brain → expand to concrete cases → generate scripts → run.
3. Oracle-source tagging end to end (weak-oracle warning when no spec grounds "correctly").
4. Surface proposed coverage to the QA for accept/edit/reject (feeds Mode A's editing).

**Tests this sprint:** NL prompt resolves to correct targets; proposed cases are valid and runnable; oracle tagging is accurate.

**DoD:** a single NL sentence yields runnable, kept-quality tests with honest oracle labels.

---

### Sprint 6 — Professional UI (app shell + core screens)

**Goal:** The light, professional interface QAs actually work in.

**Tasks:**
1. App shell: left sidebar nav, top bar with context switcher + ⌘K command palette + account.
2. Core screens: runs list, test-case editor, coverage/gap view, report/evidence viewer.
3. Data grids (TanStack Table) with status badges (color + icon + label); charts (Recharts) for coverage.
4. Apply the design system; tasteful glassmorphism on overlays/command palette only.
5. Wire screens to the APIs from Sprints 2–5.

**Tests this sprint:** Playwright tests for the tool's *own* UI (dogfooding); component tests for the editor and grid.

**DoD:** a QA can drive the full flow from the browser; UI passes its own E2E tests.

> Design help available: I can produce light-theme wireframes/mockups for these screens before the build — say the word.

---

### Sprint 7 — Evaluate / triage / reporting

**Goal:** Turn results into trustworthy signal.

**Tasks:**
1. Triage classifier: pass / real failure / likely-bad-test / flaky-or-infra.
2. Unified report: per-feature, per-layer, per-type, with evidence.
3. Coverage & gap report: uncovered endpoints/pages/journeys and role × resource cells.
4. CI output (JUnit XML) + PR summary comment.

**Tests this sprint:** triage accuracy on a labeled failure set; gap report correctness against a known repo.

**DoD:** every run produces a report a QA trusts and a gap list they act on.

---

### Sprint 8 — Mode B + change-impact + feedback loop

**Goal:** Autonomy and the start of the compounding moat.

**Tasks:**
1. Mode B: full autonomous run (propose → generate → execute → triage), no human input.
2. Change-impact: on a diff/PR, compute blast radius from the Brain, re-run only affected tests, flag newly-uncovered risk.
3. Feedback loop: write run results back to the Brain (confirmed edges, closed coverage).

**Tests this sprint:** change-impact selects the right tests for a known diff; feedback updates persist correctly.

**DoD:** a PR triggers a scoped, autonomous run with a blast-radius report; the model gets smarter per commit.

---

### Sprint 9+ — Feature-full backlog

Oracle upgrades (differential testing, interpreter-delegated assertions, mutation-kill gate, requirement-grounded oracles from business docs); self-hosted open-weight model option; control-plane + edge-runner deployment for data-residency clients; additional stack adapters (Python/FastAPI targets, more frontends); security testing (SAST/DAST); the triage-learning loop. Pull these forward as customer needs dictate.

---

## 7. Working with Claude Code

- One task = one focused session. Each task above has an acceptance check; let the test define "done."
- Keep the agent grounded: pass the relevant subgraph/context, not the whole repo (cost + quality).
- Commit per task; CI is the safety net. If Claude Code stalls on a task, that's the Antigravity fallback's moment.
- Treat the schema and design tokens as fixed inputs you hand the agent, not things it re-invents per session.

## 8. Open decisions to confirm before Sprint 0

These are assumptions baked into the plan — confirm or correct:

1. **Monorepo** (one repo, `/backend` `/frontend` `/runners` `/infra`). Assumed yes.
2. **GitHub + GitHub Actions** for repo + CI. Assumed yes.
3. **Vite SPA** for the frontend (not Next.js), since FastAPI is the backend. Assumed yes.
4. **AAHOA (Laravel)** as the Sprint 1 testbed. Assumed yes.
5. **The tool's own auth** is deferred (simple login first, SSO later). Assumed acceptable.
6. **Sprints are sized by scope, not calendar** — map them to your own cadence. Effort tags are relative (M/L).
7. **Secrets** via `.env` for dev; proper secrets management is a later (deployment) concern.
