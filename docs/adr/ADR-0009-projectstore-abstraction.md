# ADR-0009: ProjectStore abstraction

- Status: Accepted
- Date: 2026-06-17
- Deciders: Engineering

## Context

The platform persists per-project state — the test data model (TRD §3) and now
the system-model "Brain" (`model_nodes`/`model_edges`, this sprint). Today there
is exactly one deployment: a **central** control plane backed by Postgres (16 +
pgvector), and every repository is already project-scoped (Standards §14).

A future deployment is foreseen in the architecture but does not exist yet: an
**edge / portable runner** that runs inside a client network for data-residency
clients (Architecture §10; flagged as a watch-out in ADR-0001). Such a runner
needs a self-contained, file-based store rather than a shared Postgres — SQLite
is the natural fit. We do **not** want to scatter `if postgres / if sqlite`
branches through services, nor build a second backend before there is a runner
to use it.

Options considered:

1. **Hard-wire Postgres everywhere.** Simplest now, but couples every service to
   one engine; retrofitting an edge backend later means touching all data access.
2. **Build both backends now.** Premature: there is no edge runner, no SQLite
   deployment, and no tests that would exercise the second backend — pure YAGNI
   cost and untested code.
3. **Name the seam now, implement one backend.** Define a `ProjectStore`
   abstraction as the single seam for project-scoped persistence; ship only the
   Postgres backend. The SQLite/edge backend remains a documented, deferred
   decision.

## Decision

Treat project-scoped persistence as living behind a **`ProjectStore`
abstraction**:

- **Postgres backend** for the central deployment (the only backend built now).
- **SQLite backend** for the future edge/portable deployment — **recorded, not
  built**. It lands only when the edge runner actually exists and can exercise it.

This is a **documented decision**, not new code today. The existing
`ProjectScopedRepository` family (TRD §3 tables + the Brain tables) is the
concrete shape this abstraction will formalize; we keep all data access
project-scoped and engine-agnostic in spirit so the seam stays cheap to
introduce when earned. **YAGNI applies: do not add the SQLite backend now.**

## Consequences

**Easier**
- A single, named seam to add the edge/SQLite backend later without rewriting
  services; data access stays project-scoped regardless of engine.
- Keeps the door open to the data-residency edge runner foreseen in ADR-0001
  without committing to it prematurely.

**Harder / watch-outs**
- Until the abstraction is formalized in code, "behind `ProjectStore`" is a
  convention, not a compiler-enforced boundary — reviews must keep raw
  engine-specific access out of services.
- Two backends will eventually mean two code paths to test; defer that cost until
  the edge runner justifies it.

**Follow-ups**
- When the edge runner is scheduled, a follow-up ADR will specify the
  `ProjectStore` interface and the SQLite backend (schema parity, migration
  story, pgvector-vs-SQLite resolution differences).
