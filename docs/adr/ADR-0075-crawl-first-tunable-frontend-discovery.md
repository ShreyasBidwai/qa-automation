# ADR-0075 — Crawl-first + tunable frontend discovery in a mode_b run

**Status:** Accepted
**Date:** 2026-07-09

## Context

A mode_b run's frontend crawl (T4.2) discovers `page` nodes into the Brain, and those
pages become E2E targets. But the crawl phase ran at the **end** of `_run` — *after*
target selection. So the pages a run discovered only became testable on the **next**
run: a single UI run crawled but tested nothing it just found, and a user had to run
twice to test freshly-discovered (or newly-authenticated) pages. Onboarding a real app
this read as "it's not doing anything."

Separately, the crawl was hard-bounded (`max_pages=10`, `max_depth=2`, 60s) inside
`_run_crawl_phase`, so even once authentication worked, a run could only ever reach ~10
pages — far short of "test the whole frontend."

## Decision

1. **Crawl first.** Move `_run_crawl_phase` to run *before* target selection in
   `ModeBOrchestrator._run` (guarded by `ui_in_scope`, still fully defensive — a crawl
   failure never breaks the run). The crawl writes/flushes its page nodes into the
   shared session, so the very next `strategy.select(project_id)` sees them and a single
   run does **crawl → discover → select → generate → execute**. Authenticated pages a
   run finds are tested in that same run.

2. **Tunable bounds.** `crawl_max_pages` / `crawl_max_depth` /
   `crawl_time_budget_seconds` are config (defaults unchanged: 10 / 2 / 60s), threaded
   `ModeBOrchestrator(...)` → `_run_crawl_phase`'s `CrawlConfig`. Raise `crawl_max_pages`
   to cover more of the frontend — with the understanding that each page yields a few
   AI-authored E2E cases, so breadth scales generation cost/time. Bounded by design so a
   run's cost stays predictable.

## Consequences

- One UI run now meaningfully tests the frontend (including behind-login pages) instead
  of needing a second run — the behaviour users expect.
- Coverage is an explicit dial, not a hidden constant: small default for a fast run,
  larger for a wide sweep. A test (`test_mode_b_crawl.py`) pins the crawl-before-select
  ordering by asserting a crawl-discovered page is a selected target in the same run.
- The crawl still can't crash a run (defensive), and unauthenticated/no-`base_url` runs
  skip it exactly as before.
