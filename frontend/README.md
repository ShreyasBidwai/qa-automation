# frontend

React + Vite operator console for the QA Automation Platform — where QA
engineers steer the planner (modes A/B/C), edit test cases, and review runs,
coverage, and gaps. See [`../docs/01-architecture.md`](../docs/01-architecture.md)
and the UX bar in [`../docs/02-prd.md`](../docs/02-prd.md) §9.

Implemented so far: the light design system and a **System status** page that
shows live backend + database health. (More views land in later tasks.)

## Stack

Node 20 · React 18 · Vite · TypeScript 5 (strict) · Tailwind · shadcn/ui-style
primitives + Radix · lucide-react · eslint · prettier. (TanStack Table, Recharts,
Vitest, Playwright arrive with the features that need them.)

## Design system

Light mode only. Tokens are centralized — defined once as CSS variables in
[`src/index.css`](src/index.css) and exposed to components through the Tailwind
theme in [`tailwind.config.js`](tailwind.config.js). Components reference
semantic classes (`bg-surface`, `text-foreground`, `bg-status-pass-bg`, …) and
never raw hex. Tinted-neutral (zinc) base, one restrained indigo accent for
primary actions/active state, and semantic status colours (pass/fail/flaky/
info) each with a light badge variant. Status is always conveyed by **colour +
icon + label**, never colour alone (PRD §9).

## Structure (Standards §5)

Feature-foldered; presentational components vs. container hooks; all data access
through a typed API client.

```
src/
  lib/api/        typed client + response types
  components/ui/  shadcn-style primitives (badge, button, card)
  components/     shared presentational components (StatusBadge, StatusRow, AppShell)
  features/system-status/   page + useSystemStatus hook + status derivation
```

## Configure

Copy [`.env.example`](.env.example) to `.env`. `BACKEND_PROXY_TARGET` points the
Vite dev-server proxy at the backend (the `backend` service in compose, or
`http://localhost:8000` for host-only dev), so the browser stays same-origin and
no CORS config is needed. Only `VITE_`-prefixed vars reach the browser — never
put secrets in them (Standards §6).

## Run & test

Served by the root `Makefile` / `docker compose`:

```bash
make up        # start frontend (+ backend, Postgres) — dev server on :5173
npm run lint   # eslint
npm run format # prettier --check
npm run build  # tsc -b + vite build
```
