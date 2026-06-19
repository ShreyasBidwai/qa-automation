# ADR-0015: Runtime frontend crawler vs per-stack source adapter

- Status: Accepted
- Date: 2026-06-18
- Deciders: Engineering

## Context

The Brain already learns the **backend** by parsing source via stack-specific
adapters (T2.2 LaravelIngester: `route:list` + php-parser). Sprint 4 needs the
**frontend** in the Brain too — pages, their forms/interactions, and crucially
which backend endpoints each page calls (the cross-layer bridge that lets us
plan UI tests and trace coverage end-to-end).

How should we discover the frontend?

1. **Per-stack source adapters** — parse Blade templates, then Livewire, then a
   React/Vue bundle, etc. Each is a new parser, each couples us to a framework
   and its version, and SPA frontends (a compiled JS bundle) are nearly opaque to
   static parsing. Worst of all, *what a page actually calls* is a runtime fact —
   static parsing infers it at best.
2. **Runtime crawl** — drive the *running* app in a real browser, read the
   rendered DOM, and intercept the network. The target is the deployed app, so
   the rendered result is identical regardless of stack; the API calls a page
   makes are observed, not guessed.

The platform already ships a pinned Playwright/browser image (T4.1) we can reuse.

## Decision

**Discover the frontend by runtime crawl, stack-agnostically** — a
`FrontendCrawler` drives the running app in a browser and reads DOM + network; it
never parses frontend source and makes no framework assumptions. A bounded BFS
(hard caps on pages, depth, time; never leaves the target origin) yields page
snapshots that are written to the Brain as idempotent, project-scoped upserts
(source_sha + content_sha, ADR-0010 / T2.6):

- `page` nodes (identity, title, forms, key elements);
- page → page `navigates` edges (observed links — new `edge_kind`, migration 0011);
- page → endpoint `calls` edges wherever an intercepted xhr/fetch matches an
  existing endpoint node (exact, else `{param}` template) — **observed, not parsed**.

The browser layer (`PlaywrightPageFetcher` + a Node `crawl_page.mjs` driver)
reuses the T4.1 image; the BFS, caps, matching, and Brain writes live in Python
so they are unit-testable with **injected snapshots and no browser**. Auth is a
configurable login step; credentials travel over stdin and are never logged.

Source adapters are **not** removed — they remain the right tool for the backend
(routes/validation/ORM are static facts). The crawler is the frontend's, and the
*observed* call edge is something no static parse can assert.

## Consequences

**Easier**
- One crawler covers Blade/Livewire/React/Vue/anything — no per-stack frontend
  parser to build or maintain.
- The page→endpoint bridge is grounded in observation (real calls the app made),
  with a confidence that reflects exact vs templated matches.
- Reuses the existing pinned browser image; the heavy lane already exists.

**Harder / watch-outs**
- A crawl only sees what it reaches: pages behind complex auth, deep flows, or
  client state may be missed → hard caps + a configurable login step, and crawl
  results are additive (a later crawl extends coverage).
- Observation is as good as the interactions performed; this task loads pages and
  captures their calls but does not yet submit forms or click through flows
  (a follow-up).
- A new `navigates` edge kind is forward-only (an added enum value can't be
  dropped without recreating the type).

**Follow-ups**
- Drive form submissions / multi-step flows to observe more endpoints.
- The AAHOA-specific adapter/config (login flow, start URLs) on top of this
  generic crawler.
