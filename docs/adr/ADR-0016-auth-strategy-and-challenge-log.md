# ADR-0016: Pluggable AuthStrategy + interim manual OTP + challenge log

- Status: Accepted
- Date: 2026-06-18
- Deciders: Engineering

## Context

The frontend crawler (T4.2) and authenticated runners need a **logged-in session
against the live target**. The crawler had a basic per-page stdin-credentials
login baked into its browser layer — a second, ad-hoc auth path that re-logged in
on every page and could not handle OTP/2FA.

Most real targets gate login behind a second factor. We must reach authenticated
pages, but we will **not** crack or bypass MFA — OTP/2FA is *configured*. Right
now there is no data on *which* challenge types real targets actually use, so
committing to an automated solution (TOTP vs email vs SMS) would be a guess.

Forces:
- One auth path, pluggable like the other providers (AIProvider / EmbeddingProvider
  / GitProvider), so callers don't branch on auth.
- Ship something usable now (a human can complete MFA) without building automation
  we can't yet justify.
- Never log/persist secrets (code, password, full identifier) — Standards §7/§18.
- Enter OTP at most once per run (a session, not a login per page).

## Decision

**Introduce an `AuthStrategy` contract** (`app/auth/`): `login(...) -> AuthSession`,
where `AuthSession` wraps a reusable Playwright **storageState** + metadata.
Selected from an `AuthVariant` (`none`, `test_bypass`, `totp`, `email_otp`,
`sms_otp`, `manual`) via a `build_auth_strategy` registry, mirroring the existing
provider factories.

Ship only:
- `NoAuthStrategy` (empty session), `StubAuthStrategy` (tests), and
- **`ManualOtpStrategy`** (interim): drives username/password in a browser
  (`LoginBrowser` seam; real impl reuses the T4.1 Playwright image), detects the
  challenge, and obtains the code from an injected **`OtpProvider`** (an
  interactive prompt in real use; a canned value in tests) — the tester reads it
  off their own device. The resulting session is **cached by `(project_id,
  account)` and reused until expiry**, so OTP is entered at most once per run.

The automated variants (`totp`/`email_otp`/`sms_otp`) are **declared behind the
same contract but parked** — their `login` raises `NotImplementedError` pointing
at docs/parking-lot.md.

**The crawler delegates to `AuthStrategy.login()`** (defaults to `NoAuthStrategy`)
and replays the session's storageState into each page fetch — one auth path, not
two.

**Challenge log → a DB table.** Every login *attempt* appends a row to a new
project-scoped, append-only `auth_challenge_log` table (migration 0012):
`target_url`, detected `challenge` (none/otp/2fa), `channel`, `outcome`, a
**redacted** `account_label`, and a timestamp. It stores **no secrets**.

*Why a table over an append-only file:* it is project-scoped and tenancy-filtered
like the rest of our data, queryable for the analysis that picks the first
automated strategy, and survives/relocates with the database — a flat file would
need its own rotation, tenancy, and query tooling. It is strictly append-only
(rows are facts), so the table stays simple.

## Consequences

**Easier**
- One pluggable auth path for the crawler and (later) runners; swapping in an
  automated strategy is a registry change, not a caller change.
- We can reach MFA-gated pages today without building — or weakening — anything.
- We will choose the first automated strategy from **real data** (the challenge
  log), not a guess.

**Harder / watch-outs**
- The manual strategy needs a human in the loop per run (until expiry) — fine for
  interim/operator-driven runs, not for unattended CI.
- The real `PlaywrightLoginBrowser` (Node IPC for the mid-flow code) is interim
  infrastructure exercised manually, not by the fast tests (which inject a fake
  browser); the strategy logic, caching, redaction, and logging are tested.
- Secrets discipline is load-bearing: the code/password/full number must never
  reach the log or stdout — enforced by redaction + passing creds over stdin.

**Follow-ups**
- Pick + build the first automated `AuthStrategy` from the challenge-log data
  (docs/parking-lot.md).
- Have authenticated runners consume `AuthStrategy` the same way the crawler does.
