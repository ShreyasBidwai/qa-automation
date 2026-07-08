# ADR-0071 — Staff impersonation: auditable, time-boxed, secret-blind

## Status

Accepted. Extends the operator console (ADR-0068).

## Context

Support needs to see exactly what a customer sees to diagnose a problem ("your run looks
red — let me look"). Reproducing a tenant's view without their password requires the
staff member to act *as* a tenant user for a short while. Impersonation is powerful and
easy to get wrong (invisible act-as, indefinite windows, privilege escalation, secret
exposure), so the mechanism has to be safe by construction.

## Decision

A `MANAGE`-tier staff permission (`IMPERSONATE`, held by superadmin + support) mints a
short-lived session *for* a target tenant user, marked and audited.

- `POST /admin/users/{id}/impersonate` mints a normal `UserSession` for the target with a
  fresh opaque token, `expires_at = now + impersonation_ttl` (30 min — a support action,
  not a login), and **`sessions.impersonated_by = <staff id>`**. The staff member uses
  that token to browse as the user.
- **Guards** (no escalation, no self-games): cannot impersonate yourself (400); cannot
  impersonate another **staff** member (403 — a support rep must not borrow a superadmin's
  powers); the target must be active (400).
- **Audited**: every impersonation appends a `staff_audit_log` entry (`user.impersonate`,
  actor + target) — the trail is the accountability.
- **Time-boxed**: the 30-minute TTL means a forgotten impersonation self-expires; normal
  `expires_at` enforcement applies.
- **Secret-blind by construction**: the minted session is an *ordinary* tenant-user
  session, so it inherits every tenant guard — org-scoped RBAC and, crucially, the
  **write-only credential vault** (ADR-0053): the impersonator, like the user, can never
  read the tenant's target secrets. No special case is needed; it falls out of not
  widening the session's authority.

## Consequences

- Impersonation is visible after the fact (audit log) and, via `impersonated_by`, a
  session is identifiable as impersonated — a UI banner is a straightforward follow-up
  (surface it on `/auth/me`).
- The blast radius is bounded: short TTL, no staff targets, full audit, and no secret
  access. The token is returned once over TLS and stored only as its hash (ADR-0030), the
  same as any session.
- It is deliberately a *fresh session*, not a token-swap on the staff member's own
  session, so revoking it (or its expiry) never touches the staff member's real login.
