# ADR-0072 — A real, org-scoped search endpoint behind the command palette

## Status

Accepted.

## Context

The top bar has shipped a disabled search box since the desktop-app layout landed
("Search is coming in a later slice") — there was no ⌘K, no way to jump straight to
a Project / Finding / Run by name. The obvious cheap version is client-side
filtering of whatever lists are already fetched, but that reads as broken the
moment an account has more projects/findings/runs than fit in one page: a match
that exists on page 3 of the findings inbox would silently not show up.

## Decision

**A real backend endpoint, not client-side filtering.** `GET /api/v1/search?q=…`
does a deterministic, indexed name lookup across the whole account — not just
whatever page happened to be loaded in the browser.

- **Org-scoped exactly like the findings inbox and account dashboard**
  (ADR-0028/0065): `OrganizationRepository.member_org_ids` resolves the caller's
  viewable orgs, and every underlying query joins to `projects` and filters
  `Project.org_id.in_(org_ids)` — a project/finding/run outside the caller's orgs
  is never returned. No per-row `authorize_*` call is needed (mirrors
  `list_open_findings`); org membership itself is the scope.
- **Deterministic ILIKE, not semantic search.** The palette jumps to a *known* name,
  it doesn't answer an open question — so this is `ILIKE '%q%'` on `projects.name`
  and `findings.title`, backed by a `pg_trgm` GIN index (migration 0035) so an
  arbitrary substring match stays an index scan as the tables grow. It deliberately
  never touches the embedding provider or the AI layer.
  - `Run` carries no free-text name of its own (TRD §3: `run_number` / `commit_sha`
    / `status`, no title column). Searching "a run by name" is therefore honestly
    "by the project it belongs to, its commit sha, or its friendly run number" —
    documented here rather than silently matching nothing.
- **The `types` filter is an allow-list, not a passthrough** (CLAUDE.md: never feed
  a client-chosen value into a query unchecked). `project` / `finding` / `run` are
  the only accepted values; an unrecognized one is a 422, not a silently-dropped
  filter. `limit` is bounded (`1..20`, default 5) and applies **per type**, so the
  worst case (`types` omitted) returns at most 15 rows — bounded regardless of
  account size, the same "no N+1 / no unbounded fan-out" discipline as the
  dashboard and open-findings readers.
- **The response is a minimal, uniform row**: `{type, id, label, subtitle, url}`.
  No secrets, no full entity payload — just enough to render a list and navigate.
  `url` is the in-app route (`/projects/{id}`, `/findings/{id}`,
  `/runs/{id}/findings`) so the frontend's command palette can `navigate()`
  directly without knowing per-type routing rules.
- **Frontend**: a new `searchApi.search()` in the typed API client, and a
  `CommandPalette` overlay (⌘K / Ctrl+K) — debounced input, a request-id guard so a
  slow response for a stale keystroke can never clobber a fresher one, full
  keyboard nav (↑↓ + Enter + Esc), and a focus trap + focus-restore matching the
  existing `Drawer` overlay's accessibility contract (ADR-0066: it renders as a
  fixed-position overlay above the page, not a route — the window still never
  scrolls).

## Consequences

- Search results are accurate at any account size — the endpoint is the same
  "batched, bounded, org-scoped" shape as every other cross-project reader,
  not a special case.
- Adding a `pg_trgm` extension is a small, permanent addition to the schema; it is
  additive and forward-only (Standards §14) and pays for itself the moment a
  project/finding name search needs to scan more than a handful of rows.
- Searching a run "by name" is a soft edge (project name / commit sha / run number,
  not a title the run itself carries) — acceptable today; a future run-naming
  feature would only need to add one more `ILIKE` clause here, no shape change.
- The palette is intentionally a name-lookup, not a Q&A surface — a future
  semantic/AI-assisted search would be a distinct capability (its own endpoint,
  its own ADR), not a widening of this one.
