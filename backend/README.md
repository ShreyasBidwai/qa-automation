# backend

FastAPI control plane for the QA Automation Platform: the REST API (`/api/v1`),
the Brain (system model over Postgres + pgvector), the planner (mode switch),
generation orchestration, evaluator/triager, reporter, and the DB-backed job
queue. See [`../docs/01-architecture.md`](../docs/01-architecture.md) and
[`../docs/03-trd.md`](../docs/03-trd.md).

> Scaffold only — no application code yet.

## Stack

Python 3.12 · FastAPI + Uvicorn · SQLAlchemy 2.x + Alembic · Pydantic v2 /
pydantic-settings · pytest · ruff · black · mypy.

## Configure

Copy [`.env.example`](.env.example) to `.env` and fill in local values
(`DATABASE_URL`, app port, AI provider mode). No secrets in VCS (Standards §6).

## Run & test (planned)

The service runs inside Docker via the root `Makefile` / `docker compose`:

```bash
make up        # start backend (+ Postgres, frontend)
make migrate   # alembic upgrade head
make test      # pytest
make lint      # ruff + black --check + mypy
```

Health: `GET /healthz` (liveness), `GET /readyz` (readiness — DB + queue).
