# runners

Per-target-stack **execution runners** (Architecture §9, TRD §8). Each runner is
a Docker image carrying the target's toolchain plus the running app and a
**writable, ephemeral test DB**, and implements the `ExecutionRunner` interface
(TRD §5): it runs generated test scripts against the running target and returns
results with captured evidence.

> Scaffold only — no application code yet. Each subdirectory will hold a
> Dockerfile and the runner adapter for its stack.

## Subdirectories

| Path          | Stack / framework                                  |
|---------------|----------------------------------------------------|
| `laravel/`    | Laravel target, Pest tests (`LaravelRunner`)       |
| `playwright/` | Browser / UI E2E via Playwright (`PlaywrightRunner`) |
| `python/`     | Python target, pytest                              |

## Rules (Architecture §9, Standards §11)

- **Dual-DB:** read-only connection to the real DB for introspection/reference;
  a separate writable test DB for execution. Never write to the read-only DB.
- **No leaks:** spun-up target apps and test DBs are torn down on completion or
  failure.
- Containers run as **non-root**, one concern per service, with healthchecks.
