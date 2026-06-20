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

See **[`docs/running.md`](docs/running.md)** to go from clone to a running stack.

## Tech stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.x + Alembic, Pydantic v2, pytest.
- **Frontend:** Node 20, React 18, Vite, TypeScript 5, Tailwind + shadcn/ui.
- **Data:** Postgres 16 + pgvector.
- **Infra:** Docker + Compose, GitHub Actions.
- **AI:** pluggable provider; the dev implementation shells out to `claude -p`.

## How to run

Clone → a running Polaris (Postgres + backend + operator console, single-origin)
for local / demo / internal use:

```bash
cp .env.example .env     # optional — every value has a built-in default
make up                  # build + start, wait until healthy, migrations applied
# open http://localhost:8080
make down                # stop (the Postgres volume persists)
```

It boots with **zero external credentials** — the run/ingest paths default to
safe stubs, so you can click through create-project → trigger-run → triage
findings immediately. See **[`docs/running.md`](docs/running.md)** for the full
walkthrough, the configuration knobs (incl. switching to real AI / runners), the
runner execution model, and the honest limitations.

Other entrypoints: `make dev-up` (Vite hot-reload dev stack), `make test`
(full suite in Docker), `make lint`.

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) and
[`docs/04-engineering-standards.md`](docs/04-engineering-standards.md) before
opening a PR. In short: trunk-based GitHub Flow off `main`, short-lived
`type/scope-short-desc` branches, Conventional Commits, small single-purpose PRs,
and no secrets in version control.

## License

Proprietary — see [`LICENSE`](LICENSE).
