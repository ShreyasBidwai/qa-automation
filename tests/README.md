# tests

Cross-cutting, platform-level tests that span more than one package (end-to-end
flows across backend + runners, contract tests, smoke checks). Package-local
unit/integration tests live with their code under `backend/` and `frontend/`.

## Layout

- `e2e/` — Playwright E2E suite. Runs in a container (browsers preinstalled) that
  loads the running frontend and asserts live behavior. See its
  [`playwright.config.ts`](e2e/playwright.config.ts).

All suites run together via `make test`, which brings the dev stack up healthy
and then runs backend pytest, frontend Vitest, and these E2E tests inside Docker
(Standards §16). Backend unit/integration tests live in `backend/tests/`;
frontend unit tests live beside their components as `*.test.tsx`.

## Standards (Standards §15)

- Test pyramid: many unit, fewer integration, few E2E.
- **Deterministic only — zero tolerance for flaky.** Quarantine + fix, never
  retry-mask.
- Fixtures/factories for data; tests isolated, parallel-safe, no shared mutable state.
- Coverage gate on changed code (start ~80% lines on backend services);
  meaningful assertions, not tautologies.
- The platform tests itself every sprint.
