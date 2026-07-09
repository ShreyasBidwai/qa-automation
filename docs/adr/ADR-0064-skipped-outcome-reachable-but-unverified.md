# ADR-0064 — A `skipped` outcome: reachable-but-unverified, so runs self-explain

## Status

Accepted.

## Context

ADR-0063 made happy characterization honest: because static generation cannot
guarantee a specific 2xx (auth / query params / data / config-gated or
conditionally-registered routes all legitimately return 4xx), a happy test asserts
only `REACHABLE` — the app handled the request without a **5xx**.

Live runs then exposed the *other* half of the problem. With only PASS / FAIL / ERROR,
a route that returned a precondition **404** had to be shoe-horned into one of them:

- Asserting `2xx` made it **FAIL** — a false failure (the login/guest/cms runs went
  0-of-N red for a reason that is not a code defect).
- Tolerating it (assert `< 500`) made it **PASS** — but then a module of endpoints that
  all 404 reads as *blindly all-green*, hiding that nothing was actually verified.

Neither is trustworthy. "All red" cries wolf; "all green" hides that the run proved
nothing. A binary pass/fail cannot represent "we reached it, it didn't crash, but we
could not verify success." (Separately, `<skipped>` from PHPUnit — e.g. the
unavailable-factory skip of ADR-0037 — was being mis-mapped to `error`.)

## Decision

**Add a third first-class outcome, `Outcome.SKIPPED`** (migration 0034 extends the
Postgres `outcome` enum). It means: *the test ran and the endpoint was reachable, but
its success could not be verified because it returned a precondition status (a
4xx/redirect: auth, a missing record, required query params, or a route not served in
the test boot).* It is **neither a pass nor a fail**.

Threaded end to end:

- **Generation** — a happy characterization renders a **three-way** outcome:
  `>= 500` → `fail` (a real defect); a non-2xx that isn't a server error →
  `markTestSkipped("reachable but unverified: HTTP {status} — …")` (the status rides
  along); a 2xx → pass, and only then are the api JSON/echo body assertions applied.
- **JUnit / Playwright** — `<skipped>` (and Playwright `skipped`) map to `SKIPPED`,
  carrying the reason. A genuine unavailable-factory skip lands here too, no longer a
  misleading `error`.
- **Pass-rate** — SKIPPED is excluded from **both** sides: `passed / (pass + fail +
  error)`. A run of only un-verifiable endpoints has **no** rate (`None`), not `0%`.
- **Run status** — a run FAILS only on `FAIL`/`ERROR`; SKIPPED never fails a run, so an
  auth-heavy module reads PASSED, not red. The live-journey step renders a distinct
  neutral "skipped" marker (never a green tick or red cross).
- **Findings** — SKIPPED is never a finding (no defect, no crash); it is surfaced as a
  **count**, not noise.
- **Reporting / dashboard** — the run summary carries the full breakdown
  (`passed / failed / errors / skipped / tests`) and the dashboard shows
  "*N/M verified · K unverified*", so an all-green wall can't hide that K endpoints only
  returned a precondition.

## Consequences

- A run **self-explains**: green means "verified success", a skip count means "reached
  but couldn't verify — here's the status and why", red means a real defect or crash.
  The operator no longer has to read logs or query the DB to understand a run.
- The bug-finding value sits where it can assert soundly — 5xx-crash detection, the
  rule-derived negatives (validation 422 / auth 401 / web session-errors), and the
  spec-grounded tier — while the honest smoke floor stops crying wolf.
- A skip is a signal to *improve verification*, not a defect: seed the record, supply
  the query params, provision the auth, or ingest a spec (→ spec-grounded) to turn a
  skip into a verified pass. A natural next step is to let an operator drill into the
  skipped list with each endpoint's observed status.
- One-way, additive migration (a new enum value; existing rows unchanged), consistent
  with 0008/0010/0011.
