# frontend

React + Vite operator console for the QA Automation Platform — where QA
engineers steer the planner (modes A/B/C), edit test cases, and review runs,
coverage, and gaps. See [`../docs/01-architecture.md`](../docs/01-architecture.md).

> Scaffold only — no application code yet.

## Stack

Node 20 · React 18 · Vite · TypeScript 5 · Tailwind · shadcn/ui + Radix ·
TanStack Table · Recharts · Vitest · Playwright · eslint · prettier.

## Configure

Copy [`.env.example`](.env.example) to `.env` and set `VITE_API_BASE_URL` (the
backend `/api/v1` URL) and the dev `PORT`. Only `VITE_`-prefixed vars reach the
browser — never put secrets in them (Standards §6).

## Run & test (planned)

Served by the root `Makefile` / `docker compose`:

```bash
make up        # start frontend (+ backend, Postgres) — dev server on :5173
make lint      # eslint + prettier
make test      # vitest (+ Playwright for E2E)
```
