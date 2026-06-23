# Polaris — Backend Sprint Plan (redesign deltas + Tier 2)

## Where this starts
The engine (ingest → Brain → generate → run → findings), all three modes, the HTTP API,
and the full UI are built and on trunk. A UI redesign is in flight (Claude Design). This
plan is the **backend** needed to: (a) make the redesigned UI fully real, then (b) take
Polaris from a working tool to a sellable product (Tier 2). AAHOA is a *validation*
exercise on the current build — not part of this plan.

**Conventions (unchanged — Claude Code should follow them):** deterministic-first;
pluggable providers; `project_id` tenancy on every entity; batched reads, no N+1; fast
lane (`make test`) unless a runner/embedding/e2e edge changes; coverage floor ~85% (100%
only on correctness-critical logic); ADR for real decisions; migrations linear off a
single head (`alembic merge` only on a head race); one branch per task off
`chore/repo-scaffold` (trunk); maker stops and reports, no self-merge.

## Sequencing at a glance
```
B1 (UI deltas) ─┬─> B2 (auth) ─┬─> B3 (teams/RBAC) ──────────────┐
                │              └─> (unblocks auth screens)        │
                │                                                  ├─> B6 (CI Action)
                └─> B4 (durable jobs) ──> B5 (execution topology) ┘
                                                                   └─> B7 (tracker export)
B8 (self-healing) — engine-side, can land later, mostly independent
```
Do **B1 first** (unblocks the redesigned UI). **B2** early (unblocks auth screens + all
multi-user work). SSO/SAML and snooze are later. The system-health-map endpoint is a small
optional add inside B1.

---

## Sprint B1 — Backend for the redesigned UI
**Goal:** wire the new screens. The redesign adds a Findings inbox, project edit/delete,
and an app-URL field that have no backend today. This makes the new UI fully real (minus
auth).

**Scope**
- **Open-findings aggregation** — `GET /findings` (global) + `GET /projects/{id}/findings`.
  Semantics (ADR): "currently open" = the **latest run per project**, joined to triage,
  **excluding** resolved / wont_fix / false_positive, **deduped by `root_cause_key`**,
  ranked by severity. Same detail+triage shape the run dashboard uses. Paginated, batched.
  Backs the Findings inbox *and* the projects-list / project-overview open-counts.
  *(Known edge, park it: if the latest run was change-impact-scoped it covers only the
  changed slice — fine for v1.)*
- **Bulk triage** — accept a list of finding ids + a status (one call) so the inbox can
  triage several at once. Per-finding logic already exists; this is the batch wrapper.
- **Project CRUD** — `PATCH /projects/{id}` (name, repo_url, app_url, stack);
  `DELETE /projects/{id}` (cascade vs soft-delete — ADR, lean to whichever loses less
  history safely). Add **`app_url`** (crawl/E2E target base URL) — migration.
- **(Optional, small) System-health-map endpoint** — `GET /projects/{id}/health-graph`:
  Brain nodes/edges with each node's worst open-finding severity, for the optional map
  screen. Skip if time-boxed.

**Deps:** none. **Lane:** fast (migration in test DB).
*This is the already-drafted `feat/findings-inbox-and-project-crud` branch, plus bulk
triage and the optional map endpoint.*

---

## Sprint B2 — Authentication core
**Goal:** give the designed sign-in / sign-up / forgot screens a backend, and lay the
foundation for everything multi-user. **Email/password first** — SSO/SAML is a later
enterprise sprint (the login mockup shows SSO as a *placeholder*, not a B2 deliverable).

**Scope**
- Users table; password hashing (argon2 or bcrypt); sessions (JWT or server-side).
- Endpoints: sign up, sign in, sign out, request password reset, reset password. Pluggable
  mailer (dev-stub logs the reset link; real SMTP later).
- Auth dependency/middleware on protected endpoints; current-user context.
- **Project ownership** — associate projects with a user; migrate existing `project_id`
  tenancy to user ownership (ADR: migration path for existing data).
- **Honesty:** drop the "SOC 2 Type II" claim from the login; keep SSO visually as an
  unbuilt placeholder, never "live", until it's actually built.

**Deps:** none (foundational). **Lane:** fast; migration.

---

## Sprint B3 — Teams, roles & access
**Goal:** real customers are teams. Wires the account/team screens and scopes projects to
orgs.

**Scope**
- Organizations/teams; membership; roles (owner / admin / member / viewer); invite flow.
- Project access scoped to team; RBAC checks on endpoints.
- Account/profile + team endpoints: profile update, change password, member list, invite,
  role change.

**Deps:** B2. **Lane:** fast; migration.

---

## Sprint B4 — Durable jobs
**Goal:** replace the in-memory `JobRegistry` + BackgroundTasks (jobs vanish on restart,
don't scale). Reliability now; prerequisite for CI and scaling.

**Scope**
- A durable queue (Arq/RQ + Redis, or DB-backed): enqueue runs, persist job lifecycle,
  survive restart, support concurrency, cancellation, retry. Swap it in **behind the
  existing RunExecutor / job seam** — the port already exists, change the implementation.

**Deps:** none (infra); can run parallel to B2/B3. **Lane:** fast + small integration
check; introduces Redis (infra ADR).

---

## Sprint B5 — Real execution topology (decouple runners)
**Goal:** close the gap packaging surfaced — runs are backend subprocesses needing every
stack's toolchain on the backend's PATH. Fine for one dev box, wrong for a deployable
product. Decouple so the control plane stays slim and real runs become turnkey.

**Scope**
- Dispatch runs to runner workers/containers (per stack: Pest, Playwright) over the durable
  queue instead of in-process subprocess. The runner images already exist for the test
  lanes — **promote them to request-time workers**.
- A run-dispatch protocol (job → runner → results back); a toolchain-present worker image.
- Makes `EXECUTOR_MODE=orchestrator` a real packaged deployment.

**Deps:** B4 (queue). **Lane:** heavy (runner edge); architecture ADR.

---

## Sprint B6 — CI integration: the Polaris GitHub Action
**Goal:** the highest-value Tier 2 feature. The market read was blunt — native CI
integration is what removes the human bottleneck, and change-impact is built for exactly
this.

**Scope**
- A GitHub Action / webhook that, on a PR, runs Polaris change-impact-scoped against the
  diff and posts ranked findings inline (check run / PR comment) with the trust marks.
- Service tokens / API auth for CI; a results format for the Action.
- Configurable gating policy (e.g. fail the check on a new critical rule-derived finding).

**Deps:** B2 (tokens), B4 (durable jobs), B5 (real execution). **Lane:** integration; ADR.

---

## Sprint B7 — Issue-tracker export (Jira / Linear / GitHub Issues)
**Goal:** the other half of triage — turn a finding into a tracked issue.

**Scope**
- `ExporterProvider` pattern + per-tracker adapters; encrypted integration creds per
  team/project.
- `POST /findings/{id}/export` → creates a pre-filled issue (plain-English title + body,
  blast path, evidence, trust mark); stores the link back on the finding.

**Deps:** B2/B3 (creds, auth). **Lane:** fast (mocked adapters) + a live smoke per tracker;
ADR.

---

## Sprint B8 — Self-healing
**Goal:** the dominant market table-stake Polaris lacks — tests that survive UI/endpoint
drift. The runtime crawler + Brain make it tractable.

**Scope**
- On a failure that looks like drift (selector/route changed, not a real bug), re-resolve
  against the current Brain/crawl and retry; **record the heal honestly** — a healed test
  is flagged, never hidden (ties to the oracle-honesty model).
- Distinguish "healed (drift)" from "real failure".

**Deps:** engine (Brain/crawler); largely independent, can land later. **Lane:** heavy; ADR.

---

## Later / parked
- **SSO / SAML** — enterprise auth, after B2/B3. Shown in the login as a placeholder; must
  not appear "live" until built.
- **Snooze** triage status — a real inbox nicety (new status + snooze-until); defer past B1.
- **Engine breadth (existing parking lot)** — mixed-framework Mode B, transitive multi-hop
  impact, more backend adapters (Django/Rails/Node), per-stack frontend source adapters,
  T4.5 cross-layer DB execution.
- **AAHOA validation** — a validation run on the current build, not a backend sprint.

## Honesty flags to carry into the UI
- Remove "SOC 2 Type II" from the login (unearned).
- SSO is designed but unbuilt — keep it visibly a placeholder until B2+SSO.
- All auth screens stay placeholders until B2.
