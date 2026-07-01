# ADR-0056: The authenticated crawl's login config lives in project settings

- Status: Accepted
- Date: 2026-07-01
- Deciders: Engineering

## Context

A run's frontend crawl (T4.2, ADR-0016) learns the target app by driving it in a
browser. Until now it crawled **unauthenticated** — it only ever saw the public,
logged-out surface, never the behind-the-login journeys that are most of a real
app. The operator's ask is explicit: Polaris should **log in and crawl the gated
pages**.

The login machinery already existed end to end and was simply not wired into runs:

- `AuthStrategy` (ADR seam) with a real `ManualOtpStrategy` that drives a browser
  login via `PlaywrightLoginBrowser` + `runners/playwright/auth_login.mjs`, capturing
  a Playwright `storageState`.
- `FrontendCrawler.crawl()` already calls `AuthStrategy.login()` once and replays the
  resulting `storageState` on every page fetch.
- `CrawlConfig.auth: AuthConfig | None` already flows from the crawl phase to the
  strategy.
- The target **account** (username + secret) is already stored encrypted in the
  credentials vault (ADR-0053) and decrypted only at use via `resolve_target_login`.

The one missing input was **where to log in**: a `login_url` and (optionally) DOM
selectors. The credentials vault deliberately stores only the account secret, not
target topology, and we did not want a schema migration for a field with no UI yet.

## Decision

**Store the per-target login config under `project.settings['auth_config']`** — a
plain dict carrying a required `login_url` plus optional selector overrides
(`username_selector`, `password_selector`, `submit_selector`, `otp_selector`,
`otp_submit_selector`, `success_selector`). The defaults baked into `AuthConfig`
cover most stacks, so `login_url` alone is usually enough.

At run start, `resolve_target_auth_config(session, project_id)` assembles an
`AuthConfig` **only when both** are present: a complete `specific_account` credential
(so we have a username + secret) AND a settings `auth_config` with a `login_url`.
The secret is pulled from the vault via `resolve_target_login` and lives only inside
the returned `AuthConfig`; its `password` field is excluded from the dataclass repr,
so it can never leak through a log line or traceback. The run executor passes the
`AuthConfig` to `ModeBOrchestrator`, which sets it on the crawl's `CrawlConfig.auth`;
absent either input, the crawl stays unauthenticated exactly as before.

OTP/2FA in an autonomous run: there is no operator to read a code, so the wired
`OtpProvider` (`autonomous_otp_unavailable`) **fails fast** instead of blocking on
stdin. The crawl phase already treats any login failure as a clean skip, so an
OTP-gated target degrades to an unauthenticated crawl rather than hanging. Use a
non-OTP test account for behind-the-gate coverage.

## Consequences

- **Additive and reversible.** No schema migration; `auth_config` is opt-in JSONB.
  Absent ⇒ today's behaviour. If we later want first-class storage (a dedicated
  table or columns on `target_credentials`), `resolve_target_auth_config` is the one
  place to change.
- **Safe by default.** The authenticated path engages only when an operator has
  explicitly set both a specific-account credential and a login config.
- **Secret hygiene preserved.** The secret is read in the clear only by the vault
  accessor, carried in a repr-masked `AuthConfig`, and never put in settings, logs,
  the run summary, or events (ADR-0053 holds).
- **No UI yet.** `auth_config` is set via the project settings JSONB (API/DB) until a
  settings UI exposes it. The backend capability lands first; the form follows.
- **Real-browser login stays in the heavy lane.** Run wiring is covered by the fast
  hermetic suite with fakes; the real `auth_login.mjs` login is exercised by the
  e2e-runner lane, unchanged.
