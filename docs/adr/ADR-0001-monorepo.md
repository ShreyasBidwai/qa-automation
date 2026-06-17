# ADR-0001: Monorepo

- Status: Accepted
- Date: 2026-06-17
- Deciders: Engineering

## Context

The QA Automation Platform is a single product made of several cooperating
parts that must evolve together:

- a **backend** control plane (FastAPI: API, planner, generation, evaluator, reporter);
- a **frontend** operator console (React + Vite);
- per-stack **runners** (`laravel`, `playwright`, `python`) packaged as Docker images;
- **infra** (Docker Compose, CI) and **docs** (architecture, PRD, TRD, standards, ADRs);
- cross-cutting **tests**.

These parts share contracts that change in lockstep — the data model and API
surface (TRD §3–4), the core interfaces (`IngestionAdapter`, `ExecutionRunner`,
`AIProvider`, `BrainResolver`, `PlannerStrategy`, TRD §5), and the dev workflow
(`docker compose up` as the canonical entrypoint, Standards §17). Architecture §2
already mandates a stack-agnostic core with thin adapters, and CI must mirror
local Compose so behavior is identical everywhere.

Options considered:

1. **Polyrepo** — one repository per component. Cross-cutting contract changes
   span multiple PRs across repos, atomic changes are impossible, version drift
   between backend/frontend/runners is likely, and a single `docker compose up`
   spanning repos is awkward.
2. **Monorepo** — one repository with a fixed top-level layout. A single PR can
   change a contract and all its consumers atomically; one CI pipeline mirrors
   the Compose stack; shared docs and ADRs live beside the code they govern.

## Decision

Use a **single monorepo** with the top-level layout fixed by Engineering
Standards §2 and Architecture §2:

```
/backend   /frontend   /runners   /infra   /docs   /tests
```

`runners/` is further split per target stack (`runners/laravel`,
`runners/playwright`, `runners/python`, per Architecture §9). Architecture
decisions live in `/docs/adr`; contracts change only via an ADR here.

## Consequences

**Easier**

- Atomic, single-PR changes across a shared contract and all its consumers.
- One CI pipeline that mirrors `docker compose up`, eliminating "works on my
  machine" drift (Standards §16–17).
- Docs, ADRs, and code reviewed together and kept in sync; one place to clone.
- Consistent tooling, branching, and Conventional-Commits conventions repo-wide.

**Harder / watch-outs**

- The repo grows large over time; CI must scope work to changed paths to stay fast.
- A single visibility/access boundary — acceptable now (one internal deployment),
  but the future **edge runner** (Architecture §10) may need code that runs in a
  client network. If/when data-residency forces separation, that split will be
  recorded in its own ADR; this decision does not preclude it.
- Path-based ownership and CI filtering become necessary as more components land.

**Follow-ups**

- `infra/` provides the Compose stack and GitHub Actions workflow wiring the
  `Makefile` targets (`up`, `down`, `test`, `lint`, `migrate`).
- Each package carries its own README explaining how to run and test it (Standards §19).
