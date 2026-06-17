# QA Automation Platform

A platform that understands a target web application (backend + frontend) and
autonomously **generates, executes, and reports tests** across all types — smoke,
happy-flow, negative, edge, E2E, user-journey, and role/profile — over a single
engine with three operating modes. It is run by QA engineers, who can edit any
test case at any time, and it treats its accumulated understanding of each system
(the "Brain") as a compounding asset.

See [`docs/01-architecture.md`](docs/01-architecture.md) for the full design,
[`docs/02-prd.md`](docs/02-prd.md) for the product requirements, and
[`docs/03-trd.md`](docs/03-trd.md) for the technical contracts.

## Operating modes

The three modes are a single switch on the **planning** layer; generation,
execution, and reporting are identical downstream.

- **Mode A** — a human populates the test plan.
- **Mode C** (default) — the AI proposes the plan from the Brain; QA steers via
  natural-language prompts and the AI owns completeness.
- **Mode B** — the AI populates and runs the plan autonomously, no human input.

## Repository layout

This is a monorepo (see [ADR-0001](docs/adr/ADR-0001-monorepo.md)).

| Path         | Contents                                                              |
|--------------|-----------------------------------------------------------------------|
| `backend/`   | FastAPI control plane (API, planner, generation, evaluator, reporter) |
| `frontend/`  | React + Vite operator console                                         |
| `runners/`   | Per-stack execution runner images (`laravel`, `playwright`, `python`) |
| `infra/`     | Docker Compose, CI, and deployment configuration                      |
| `docs/`      | Architecture, PRD, TRD, engineering standards, and ADRs               |
| `tests/`     | Cross-cutting / platform-level tests                                  |

> Application code is not present yet — this commit scaffolds the repository only.

## Tech stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.x + Alembic, Pydantic v2, pytest.
- **Frontend:** Node 20, React 18, Vite, TypeScript 5, Tailwind + shadcn/ui.
- **Data:** Postgres 16 + pgvector.
- **Infra:** Docker + Compose, GitHub Actions.
- **AI:** pluggable provider; the dev implementation shells out to `claude -p`.

## How to run (dev)

`docker compose up` is the canonical dev entrypoint, wrapped by a `Makefile` for
common commands. The Compose stack will bring up Postgres (+pgvector), the
backend, and the frontend; runners are built on demand.

```bash
# 1. Copy the environment templates and fill in local values (no real secrets in VCS)
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

# 2. Bring the stack up (Postgres, backend, frontend)
make up            # wraps: docker compose up

# 3. Run database migrations
make migrate       # wraps: alembic upgrade head (inside the backend container)

# 4. Lint and test
make lint
make test

# 5. Tear the stack down
make down          # wraps: docker compose down
```

Once running, the services are reachable at:

- Backend API: `http://localhost:8000/api/v1` (liveness `GET /healthz`, readiness `GET /readyz`)
- Frontend console: `http://localhost:5173`

> The `Makefile` targets are **declared but not yet implemented** — they will be
> wired to `docker compose` and `alembic` as the corresponding services land.

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) and
[`docs/04-engineering-standards.md`](docs/04-engineering-standards.md) before
opening a PR. In short: trunk-based GitHub Flow off `main`, short-lived
`type/scope-short-desc` branches, Conventional Commits, small single-purpose PRs,
and no secrets in version control.

## License

Proprietary — see [`LICENSE`](LICENSE).
