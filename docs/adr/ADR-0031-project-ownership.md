# ADR-0031: Project ownership + migrating existing tenancy to user ownership

- Status: Accepted
- Date: 2026-06-21
- Deciders: Engineering

## Context

Before B2 there were no users: `projects` were globally accessible (single-tenant).
B2 introduces users and must associate projects with an owner and enforce it,
**without orphaning the projects/runs/findings created before auth existed** (the
demo/seed data). Teams/RBAC are B3 — B2 is per-user ownership only.

## Decision

**Add `projects.owner_id` as a NULLABLE FK → `users(id)` (`ON DELETE SET NULL`)**
(migration 0018, linear off 0017).

**Migration path for existing rows:** they keep `owner_id = NULL`, meaning
**"legacy / unowned / shared"**. No backfill is possible (there are no users at
migration time), and nulling-out would be wrong — so NULL is a first-class state:

- **New projects** are created by an authenticated user → `owner_id = creator`.
- **Access rule (enforced in `ProjectRepository`):** an authenticated user may
  access a project iff `owner_id IS NULL` (legacy/shared) **or** `owner_id =
  current_user.id`. Project reads/writes go through `get(project_id, accessor_id)`
  / `list(accessor_id)`, so a non-owned project is simply **not found** (404) —
  the same not-found path already used everywhere; existence is not leaked.
- This **preserves all existing data**: pre-auth projects (NULL owner) stay
  reachable by any signed-in user, while every newly-created project is owned and
  private to its creator.

All `/api/v1` data endpoints now require authentication (`get_current_user`);
`/healthz`, `/readyz`, and `/auth/*` stay public.

## Why nullable + NULL-is-shared (not a backfill or hard cutover)

- **No user exists at migration time**, so there is nothing to backfill to. A
  synthetic "system user" would be a fake actor (we avoid that, cf. ADR-0027).
- **NULL = shared** keeps the existing demo/seed projects usable instead of
  locking everyone out the moment auth ships — the safe, reversible migration.
- It's a clean base for B3: teams will narrow access from "owner-or-shared" to
  "team-scoped", and a later migration can claim NULL-owner rows into a team.

## Consequences

- Ownership is enforced for all newly-created projects; legacy rows are shared
  until explicitly claimed (a future, deliberate action).
- `ON DELETE SET NULL`: deleting a user turns their projects into shared/legacy
  rather than cascade-deleting their work (history-preserving, consistent with the
  soft-delete stance of ADR-0029).
- Cross-user access returns 404 (not 403) to avoid leaking which project ids exist.
