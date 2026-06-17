# tests

Cross-cutting, platform-level tests that span more than one package (end-to-end
flows across backend + runners, contract tests, smoke checks). Package-local
unit/integration tests live with their code under `backend/` and `frontend/`.

> Scaffold only — no tests yet.

## Standards (Standards §15)

- Test pyramid: many unit, fewer integration, few E2E.
- **Deterministic only — zero tolerance for flaky.** Quarantine + fix, never
  retry-mask.
- Fixtures/factories for data; tests isolated, parallel-safe, no shared mutable state.
- Coverage gate on changed code (start ~80% lines on backend services);
  meaningful assertions, not tautologies.
- The platform tests itself every sprint.
