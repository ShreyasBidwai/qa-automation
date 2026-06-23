# ADR-0046: Pre-exposure hardening — rate limiting, password policy, coverage attribution

- Status: Accepted
- Date: 2026-06-23
- Deciders: Engineering

## Context

Before the product faces real users and networks, three hygiene gaps: the auth
endpoints had no rate limiting, new passwords were length-checked but not
strength-checked, and the coverage floor was dishonest because ASGITransport tests
under-reported API handler lines. This is hygiene, not a moat.

## Decision

### (1) Rate limiting — in-memory, per-IP, single-instance

A fixed-window `RateLimiter` (`app.core.rate_limit`) caps requests per
`name:identity` per window; a FastAPI dependency (`app.api.rate_limit.rate_limited`)
keys by client IP and applies it to the sensitive endpoints: **sign-in**, **sign-up**,
**password-reset request**. Over the limit returns a clear **`429`** with a
`Retry-After` header. Defaults (per IP per 60s, tunable via env): sign-in 10,
sign-up 10, reset 5.

- **Single-instance caveat:** counters live in this process's memory. Behind
  multiple replicas each holds its own window (effective limit = per-replica), and a
  restart clears them. Acceptable to blunt obvious abuse before launch; a shared
  store (Redis) is the next step for horizontal deployment. **No persistence → no
  migration.**
- **Determinism:** the clock is injectable, so the window/reset is tested with a fake
  clock — no `sleep`, no flakiness. The default test app uses very high limits
  (conftest) so ordinary tests never trip it; the rate-limit tests inject small,
  clock-controlled limits.
- **Proxy caveat:** the key is `request.client.host`; behind a trusted reverse proxy
  that's the proxy IP unless `X-Forwarded-For` is honored upstream — a deployment
  concern, not handled here.

### (2) Password policy — new passwords only

`app.core.password_policy.validate_password` enforces a **≥8 character floor** (what
the UI implies) plus two cheap strength checks: not all-numeric, and not in a tiny
blocklist of the most-guessed passwords. Honest, **voiced** error messages (e.g.
"Password can't be all numbers — add letters or symbols."), surfaced as a `422`. It
is deliberately NOT a breach corpus or a zxcvbn estimator.

Applied via a `NewPassword` validated type to **sign up**, **password-reset confirm**,
and the **new** password on change — never to sign-in or a current password. Only
**input validation** is added; **no auth success-response shape changes**.

### (3) Coverage attribution — credit ASGITransport-driven handlers

The under-reporting was real: tested handler lines after a DB `await` (e.g. the 409
duplicate-signup branch) showed as missing. Cause: SQLAlchemy's async runs on
**greenlets**, and coverage was losing the resumed coroutine after a greenlet switch.
Fix: `concurrency = ["thread", "greenlet"]` in `[tool.coverage.run]` **plus**
`COVERAGE_CORE=ctrace` on the test service (the classic C-trace core supports greenlet
concurrency reliably; the Python 3.12 default `sys.monitoring` core does not). Effect:
`app/api/auth.py` went **67% → 84%** with the same tests (the remaining gap is
genuinely-untested handlers). The coverage floor is now honest.

## Consequences

- **Frontend-visible (flagged):** the auth endpoints can now return **`429`** (new —
  the UI should show "too many requests, try again shortly" and may read
  `Retry-After`), and weak-password sign-up/reset returns **`422`** with a voiced
  `detail` message. No success-response shape changed.
- Coverage now reflects reality, so the floor means what it says; API coverage is
  measured accurately going forward.
- Rate limiting is best-effort single-instance until a shared store lands.
