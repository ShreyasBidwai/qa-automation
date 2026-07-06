# ADR-0063 — Route-class-aware generation (web vs api): honest oracles, no guessed status

## Status

Accepted.

## Context

A real Mode-B run against an auth-heavy module (login) failed **every** generated
test. The evidence: each "happy characterization" test did `getJson('login/apple')`
and `assertStatus(200)`, and every one got a **404** → all triaged `bad-test`. The run
wasn't a platform failure — the triage correctly flagged the tests as noise — but the
tests were **un-passable by construction**.

Root cause: **generation assumed every route is a JSON API endpoint** with a canonical
REST status and a JSON body. That is false for Laravel's *web* route class (session /
CSRF / HTML / redirects), which is most of a login/auth surface. The single assumption
produced a whole family of false failures:

1. **Happy status guessed from the verb** — `_success_status()` asserted an exact
   `200`/`201`/`204`. An OAuth route (`login/apple`, `login/google`) really returns a
   **302** redirect; a POST may return `200`, not `201`.
2. **Happy assumed a JSON body** — `getJson` + `assertIsArray($response->json())` on a
   web route that returns HTML/a redirect.
3. **Path-param happy 404** — path params were filled with `1` and no row was seeded,
   so `GET /resource/{id}` route-model-binding returned **404**.
4. **Auth-unauthenticated assumed 401** — a web route's `auth` middleware **redirects
   to `/login` (302)**, it does not return 401 (that is the api behaviour).
5. **Web validation assumed 422 JSON** — a web validation failure is a **302 redirect
   back with session errors**, not a 422 JSON envelope.

Crucially, the signal to tell the two classes apart was **already in the Brain**: the
Laravel ingester records each route's `middleware` on its endpoint node (`ingester.py`).
Generation simply collapsed it to an `auth_required` bool and threw the rest away — so
**no re-ingest is needed** to fix this.

## Decision

**Generation is route-class-aware.** `EndpointSpec` carries `is_api` (derived from the
route's middleware — `api` group → api, `web` → web, with a conventional `api/` URI-prefix
fallback; defaults to api so nothing that predates this silently changes). The
deterministic planner then tags each case with an **assertion semantics** —
`ResponseExpectation` — instead of a bare status number, and the renderer maps each to
the exact PHPUnit call:

| Case | api (JSON) route | web (session) route |
|---|---|---|
| Happy (no bound param) | `SUCCESS_JSON` — `assertSuccessful()` (any 2xx) + JSON body | `REACHABLE` — `< 500` only |
| Happy (model-bound path param) | `REACHABLE` — `< 500` only | `REACHABLE` |
| Unauthenticated | `STATUS` 401 | `REDIRECT` — redirect to login |
| Validation failure | `STATUS` 422 + `assertJsonValidationErrors` | `REDIRECT_WITH_ERRORS` — `assertSessionHasErrors` |

The guiding principle is **honesty over precision (ADR-0025)**: static generation cannot
observe the running app, so a characterization test must assert only what the
framework *guarantees* for the route's class — never a guessed exact status. Asserting
a hardcoded `200` was not characterization at all; it was an invented spec.

The strong `SUCCESS_JSON` (2xx + JSON) assertion is earned only by the one case we can
actually set up: an **api** route driven with a complete, valid payload and **no
un-seedable path param** — the CRUD happy path. For everything else the route's success
is **not knowable statically**: a **web** route may be auth/OAuth-gated, redirect, or be
**conditionally registered** (config-gated) so the running app returns 404 for a route
the static parser saw (ADR-0055); a **model-bound path param** we can't seed 404s on the
missing row. There the honest floor is `REACHABLE` — the app *handled* the request
without a **5xx** (a `401/403/404`/redirect is a real precondition, not a defect). This
is what stops the false-failure noise; the rule-derived tier still carries the precise,
framework-guaranteed checks (422/401 on api, redirect/session-errors on web), and a real
`5xx` crash still fails.

**Reporting fidelity.** A finding whose case never linked a Brain node used to read
"failure at **unknown target**". The failing case's stable `case_key` already names the
endpoint (`GET /login/apple::happy::happy`), so the assembler falls back to it — the
finding now reads "failure at `GET /login/apple`" and groups per endpoint. Additive and
last-resort: it never overrides a real cross-layer location.

## Consequences

- An auth/OAuth/web module is testable: happy tests pass when the route legitimately
  redirects, unauthenticated tests assert the redirect-to-login, web validation asserts
  session errors. The login module goes from 0/7 to a truthful pass rate.
- Characterization is honest: it pins a band, not a guess, so it stops manufacturing
  `bad-test` noise while still catching 5xx regressions and removed routes.
- No migration / re-ingest: `is_api` is derived from middleware already on the node;
  older Brains that captured no middleware fall back to the `api/` URI-prefix heuristic.
- The renderer's assertions are AI-authored but now driven by an explicit
  `expected.assert` directive per case, so the model is told *exactly* which PHPUnit
  call to emit instead of inferring one (the inference is what produced the bad 200s).
- Residual honesty limit: a web `*/callback` route hit without OAuth state may still
  `5xx`; that surfaces as a finding, which is correct — an unhandled callback IS worth
  seeing. Path-param happy paths only assert "no server error", trading some strength
  for the truth that we cannot seed an arbitrary bound record statically.
