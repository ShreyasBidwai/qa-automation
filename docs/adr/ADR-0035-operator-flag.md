# ADR-0035: Operator access is an instance-level `is_operator` flag, not an org role

- Status: Accepted
- Date: 2026-06-21
- Deciders: Engineering

## Context

B4 adds a minimal **operator status view** — queue depth, running/stuck/failed
jobs, runner health. This surface is **cross-tenant**: it reports on jobs across
*all* organizations, so it cannot be governed by the org RBAC from B3 (ADR-0033).
An org owner must not see another org's jobs; operator visibility is a property of
the *person running the instance*, not of any membership. We need an instance-level
gate, and to decide its mechanism.

The options: an **`is_operator` boolean on `users`**, or an **env allowlist** of
operator emails.

## Decision

**An `is_operator` boolean column on `users` (default `false`), checked by an
`operator_user` dependency that 403s a non-operator.** It is granted **out of
band** — by a DB update / seed — with **no API to set it**. There is deliberately
no "promote to operator" endpoint: the flag is powerful (cross-tenant), rare, and
must not be reachable through the normal product surface.

### Why a column, not an env allowlist

- It's queryable and lives with the user it describes (joins, audits, "who are the
  operators?" is a `SELECT`).
- It survives email changes (B3 lets users change their email) — an allowlist keyed
  on email would silently break.
- We're already adding migration 0020 for the `jobs` table, so the column is free;
  no new config-parsing or env-drift across environments.

An env allowlist's only advantage — "no schema change" — doesn't apply here, and it
trades a typed, queryable fact for stringly-typed config that's easy to misconfigure
per-environment.

### Enforcement

- `operator_user` builds on `get_current_user` (so unauthenticated → 401) and then
  requires `is_operator`; a logged-in non-operator gets **403** (it's an
  authenticated authorization failure, and the `/ops` path is not a secret). This is
  distinct from the data-plane's 404-for-outsiders rule (ADR-0033), which hides
  per-tenant resource existence — the operator surface isn't tenant-scoped, so
  there's nothing to hide, and 403 is the honest answer.
- Operator endpoints live under `/api/v1/ops` and read **across tenants** by design
  (that is the whole point of the surface).

## Consequences

- A simple, queryable, email-change-proof gate for a cross-tenant surface, with no
  new config surface and no privilege-escalation path through the API.
- This is the seed of ops visibility, not a platform admin panel (parked): no
  mutation endpoints, no per-tenant impersonation — read-only queue/runner health.
- Granting operator access is an operational action (DB/seed), which is appropriate
  for a powerful, rarely-changed instance privilege.
