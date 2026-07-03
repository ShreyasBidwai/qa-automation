# ADR-0061 — Module-scoped runs (test one feature area, including its frontend)

## Status

Accepted.

## Context

An autonomous run (Mode B) tested either **everything** (full sweep) or **what
changed** (change-impact). But a QA often wants to test just one feature area — "run
the Orders module" — without a full sweep or a changeset. There was no way to say that.

A related question: if you scope to a module, can you test its **frontend**? The
answer had to fall out of the architecture, not a new subsystem.

## Decision

**A "module" is a DERIVED grouping, not a stored entity.** A testable Brain node's
module is the first meaningful segment of its URI/path, after any `api`/version prefix
(`app/brain/modules.py`): `POST api/v1/orders`, `GET api/v1/orders/{id}` and the page
`/orders` all belong to `orders`. Deriving (rather than storing) means modules appear
the moment the model is built and need no migration or re-ingest.

- `GET /projects/{id}/modules` returns the derived modules with per-kind counts
  (`endpoint_count` = API targets, `page_count` = UI/frontend targets), most targets
  first — powering a searchable picker in the run form (VIEW-gated, org-scoped).
- Mode B gains an optional `modules` scope on the request, threaded to `ModeBBounds`
  and applied as a **target filter** (`targets_for_modules`) right after the layer
  filter (`targets_for_layers`) — exactly the same shape, so it's a small, proven
  addition, not a new selection strategy.

**Testing a module's frontend — the composition insight.** A module holds both API
endpoints (ENDPOINT nodes → API tests) and UI pages (PAGE nodes → the crawl + E2E).
The module filter and the layer filter **compose**:

- module `orders` ∩ layer `ui` → the Orders **frontend** (its page targets drive the
  crawl + Playwright E2E),
- module `orders` ∩ layer `api` → the Orders endpoints (PHPUnit),
- both layers → the whole module.

So "test the frontend of the Orders module" needs no new execution path — it is the
existing UI-layer generation (ADR-0060 crawl/E2E) narrowed to that module's pages. In
the run form, choosing "Test specific modules" + leaving UI on does exactly this.

### Security

A module key is only ever **string-compared** to a node's derived key — never fed into
SQL, a path, a URL host, or an argv/command element — so it carries no injection
surface. The filter only ever NARROWS within the project's own targets, so an unknown
or spoofed key simply matches nothing (it can never reach another tenant's nodes). The
request validator lower-cases, de-dupes, and bounds the list (≤200 keys, ≤128 chars
each) to cap resource use. The endpoints are project-scoped and RBAC-gated (VIEW to
list, RUN to start).

## Consequences

- A QA can run one feature area — and specifically its frontend or its API — in a few
  clicks, without a full sweep or a changeset.
- Modules stay in sync with the code for free (re-derived each request from the Brain);
  a rename in the app renames the module with no migration.
- Derivation is heuristic (first path segment). An app with an unusual routing scheme
  may group imperfectly; the picker shows the counts so the operator can sanity-check,
  and the model can be rebuilt to refresh. A future iteration could let ingestion
  annotate an explicit module per route.
- Also shipped alongside: the Project view's **Connectors** card surfaces the planned
  Gitea + project-management integrations as "coming soon" (static, no backend yet).
