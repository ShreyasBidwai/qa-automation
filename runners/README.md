# runners

Per-target-stack **execution runners** (Architecture §9, TRD §8). Each runner is
a Docker image carrying the target's toolchain plus the running app and a
**writable, ephemeral test DB**, and implements the `ExecutionRunner` interface
(TRD §5): it runs generated test scripts against the running target and returns
results with captured evidence.

The runner *adapters* live in the backend (`backend/app/execution/`, behind the
`ExecutionRunner` interface); each subdirectory here holds the **image** that
carries that stack's toolchain and runs the adapter + its integration tests.

## Subdirectories

| Path          | Stack / framework                                  | Status |
|---------------|----------------------------------------------------|--------|
| `laravel/`    | Laravel target, Pest tests (`PestRunner`)          | **implemented** — `make test-runners` |
| `playwright/` | Browser / UI E2E via Playwright (`PlaywrightRunner`) | scaffold |
| `python/`     | Python target, pytest                              | scaffold |

## `laravel/` (PestRunner)

`runners/laravel/Dockerfile` builds a non-root image with PHP 8.2 + Composer +
Pest + `nikic/php-parser` **and** Python, so the `PestRunner` and its pytest
integration tests run against the bootable fixture app
(`backend/tests/fixtures/laravel-app/`). `make test-runners` builds it and runs:

- the **runner integration test** — `PestRunner` executes a representative
  generated suite (happy → pass, missing-required/unauthorized/unique-duplicate
  → expected-failure detected as pass, plus a deliberately-wrong test → fail) and
  maps each to a `Result` outcome with captured JUnit evidence;
- the **PHP-helper shape test** — the real T1.3 `extract_validation.php` run
  against the fixture, asserting its JSON matches the Python normalizer contract.

The target boots against **in-memory sqlite** (the writable, ephemeral test DB),
so there is no Postgres and nothing to leak.

## Rules (Architecture §9, Standards §11)

- **Dual-DB:** read-only connection to the real DB for introspection/reference;
  a separate writable test DB for execution. Never write to the read-only DB.
- **No leaks:** spun-up target apps and test DBs are torn down on completion or
  failure.
- Containers run as **non-root**, one concern per service, with healthchecks.
