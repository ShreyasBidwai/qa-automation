# infra

Infrastructure and developer/CI wiring for the QA Automation Platform.

> Scaffold only — no configuration files yet.

## Planned contents

- **`docker compose`** — the canonical dev stack (Postgres 16 + pgvector,
  backend, frontend; runners built on demand). `docker compose up` is the dev
  entrypoint (Standards §17); the root `Makefile` wraps it.
- **GitHub Actions** — CI that runs **inside Docker**: build → lint → typecheck →
  unit → integration → (E2E where relevant), fail-fast, no merge on red. CI
  mirrors local Compose so "works on my machine" can't happen (Standards §16).

## Conventions (Standards §17)

Multi-stage builds; pinned base images and dependency versions; `.dockerignore`
to keep contexts small; containers run as non-root; healthchecks on every
service; `depends_on` with condition checks.
