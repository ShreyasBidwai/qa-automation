# PRD — QA Automation Platform

*Status: baseline (v1). Companion to `01-architecture.md`, `03-trd.md`, `04-engineering-standards.md`.*

---

## 1. Summary

A QA platform that understands a target web app and generates, runs, and reports tests across all types, operated by QA engineers who keep full editorial control. It removes the two biggest QA bottlenecks — knowing *what* to test on a given system and the drudgery of *scripting* it — while keeping tests trustworthy (assert correctness, not just current behavior) and portable.

## 2. Problem & opportunity

Teams ship faster than they can test. Writing and maintaining tests is slow and brittle; coverage decisions are ad hoc; AI test generators mostly emit characterization tests that cement current behavior and assert trivially. No tool unifies code understanding, requirement intent, and cross-layer execution into one operator-controlled workflow. Opportunity: a tool that understands the system, proposes high-value coverage, scripts it deterministically where possible, and lets a QA stay in command.

## 3. Goals & non-goals

**Goals:** generate + run + report full-stack tests; three control modes; QA-editable versioned cases; honest oracle labeling; portable output; per-project understanding that compounds; runs in Docker; tests itself every sprint.

**Non-goals (v1):** replacing QA judgment; multi-language target support beyond the first stack; security pen-testing; formal verification; mobile-native targets; on-prem edge deployment (later).

## 4. Personas

- **Priya — QA engineer (primary operator).** Wants coverage without writing every script by hand; needs to edit/override anything the AI produces; distrusts black-box "AI decides everything." Lives in the tool daily.
- **Rohan — engineering lead.** Wants confidence that PRs don't break behavior, a coverage/gap view, and CI gating. Reviews reports, not individual tests.
- **Datagrid (customer zero).** Uses the tool internally to raise delivery margin on client projects before productizing.

## 5. The three modes (product framing)

- **Mode A — author & script.** QA writes cases (recorded flow, structured, or NL); tool generates scripts (deterministic-first, AI fallback). *QA owns coverage completeness.* For teams that distrust AI-chosen coverage.
- **Mode C — hybrid (default).** AI proposes scenarios/cases from the Brain; QA steers with NL prompts ("test the loyalty discount"). AI owns completeness; QA edits/accepts/rejects. The everyday mode.
- **Mode B — autonomous.** AI proposes, generates, runs, triages with no human input. For hands-off coverage and CI.

All three share one engine; the only difference is who populates the test plan.

## 6. Features (epics, MoSCoW, sprint mapping)

| Epic | Priority | Sprint |
|---|---|---|
| Dockerized stack + CI + design system | Must | 0 |
| Backend test generation + execution (walking skeleton) | Must | 1 |
| Repo/DB ingestion + lightweight Brain (NL resolution) | Must | 2 |
| Editable, versioned test cases (Mode A core) | Must | 3 |
| Frontend E2E + cross-layer linking | Must | 4 |
| Mode C + NL prompting | Must | 5 |
| Professional operator UI | Must | 6 |
| Evaluate/triage + coverage & gap reporting | Must | 7 |
| Mode B + change-impact + feedback loop | Should | 8 |
| Oracle upgrades, self-host model, edge runner, multi-stack, security | Could/Won't-v1 | 9+ |

## 7. Key user journeys

1. **Onboard a project:** connect repo (read-only) + running app + test users per role → tool ingests, builds the Brain, shows the system model.
2. **Mode C prompt:** QA types an NL intent → AI proposes cases (labeled by oracle source) → QA edits/accepts → tool runs → report with evidence.
3. **Edit a case:** QA opens any generated case, edits steps/assertions → edit is versioned and locked so re-generation never clobbers it.
4. **Review a run:** Rohan opens the run report → sees pass/fail by feature/layer, triage labels, coverage gaps, and a PR comment in CI.

## 8. Functional requirements (selected)

- FR-1 Connect a project with read-only repo + read-only DB introspection + running-app URLs + role test accounts.
- FR-2 Generate tests of every supported type; tag each assertion's `oracle_source`.
- FR-3 Execute across layers; capture evidence (screenshots, traces, logs, response/DB state).
- FR-4 Let a QA author, edit, lock, and re-run any case; edits survive re-generation.
- FR-5 Mode C resolves NL prompts to concrete cases via the Brain; warns when "correctly" lacks a spec.
- FR-6 Produce a coverage & gap report incl. role × resource matrix.
- FR-7 Emit portable test code + JUnit CI output + PR summary.
- FR-8 Mode B autonomous runs + change-impact selection on diffs.

## 9. Non-functional requirements

- **Trust:** never present a tautological/weak oracle as a strong one; label oracle source; mutation-gate later.
- **UX:** light, professional, content-first; progressive disclosure; status conveyed by color **and** icon/label; ⌘K command palette; sub-second interactions for list/edit.
- **Privacy/security:** least-privilege read-only access; per-project isolation; secrets in env; no client code leaves the deployment boundary (edge runner later for stricter clients).
- **Reliability:** runs in Docker identically anywhere; graceful start/stop; queued jobs are retryable and idempotent.
- **Portability:** output is standard framework code, committable to the target repo.

## 10. Success metrics

- % of generated tests a QA keeps without edit (target rising over time).
- Mutant-kill rate of generated suites (proxy for non-tautological oracles).
- Time-to-first-useful-suite for a newly onboarded project.
- Coverage of behaviors/endpoints/roles closed per week.
- Internal: QA hours saved on Datagrid client delivery.

## 11. Out of scope / future

Multi-language targets, security testing, formal verification, requirement-grounded oracle synthesis, self-hosted models, edge-runner deployment, the triage-learning loop — all post-v1, pulled forward by customer need.

## 12. Assumptions & dependencies

Monorepo + GitHub Actions; Vite SPA; AAHOA (Laravel) as first testbed; deferred in-tool auth (simple login first); `claude -p` for dev; `project_id` tenancy from day one.
