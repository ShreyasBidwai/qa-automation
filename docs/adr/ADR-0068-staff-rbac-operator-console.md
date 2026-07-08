# ADR-0068 — Staff RBAC: an operator/admin console that spans tenants

## Status

Accepted. Supersedes the operator-flag decision of ADR-0035.

## Context

ADR-0035 gave us a single boolean `users.is_operator` — a read-only, cross-tenant
"seed of ops visibility," explicitly parked as "not a platform admin panel: no
mutation endpoints, no impersonation." As we approach go-to-market we need a real
operator console: staff must inspect and act across tenants (retry a job, suspend an
abusive org, adjust billing, read an audit trail). A god-boolean is the wrong
primitive for that — it cannot express least privilege or separation of duties, and
granting mutation power to everyone flagged an "operator" is unsafe.

## Decision

Replace the boolean with an instance-level **staff role** and a permission matrix,
mirroring the org RBAC of ADR-0033 but at the platform (cross-tenant) tier.

- `StaffRole` (`superadmin` / `support` / `billing` / `read_only_ops`) on
  `users.staff_role`; NULL means the user is not staff.
- `StaffPermission` + a role→permission matrix in `app.core.staff_permissions`, with
  one predicate `staff_role_can`. Every role shares a read-only base; mutations are
  sliced by duty: `support` acts on jobs and impersonates but never touches money;
  `billing` owns billing but not jobs/impersonation; `read_only_ops` mutates nothing;
  `superadmin` is a superset.
- `app.api.staff_authz.authorize_staff(user, permission)` — the single enforcement
  path (DB-free; the role is an attribute of the user). An authenticated non-staff
  user gets 403 (an authorization failure, not a hidden per-tenant resource — the
  same convention ADR-0035 chose); a staff member lacking the permission also 403.
  `require_staff(<permission>)` wraps it as a FastAPI dependency for admin routes.

Existing `is_operator = true` users are backfilled to `read_only_ops` — least
privilege, preserving their prior read-only cross-tenant visibility without granting
any mutation. `is_operator` is retained (deprecated) and still honoured by the
existing read gate during the transition; a later migration can drop it.

## Consequences

- The operator console can grow mutation endpoints safely: each gates on a specific
  `StaffPermission`, so a support rep can never issue a refund and a billing analyst
  can never cancel a job.
- Staff access becomes grantable in-band (a superadmin promotes/demotes via the admin
  API — forthcoming) and auditable, instead of only an out-of-band DB flip.
- The customer-facing org RBAC (ADR-0033) is untouched and remains the only authority
  inside a tenant. Staff authorization is a **separate, explicit path** — never a
  short-circuit bolted into `authorize_org`/`authorize_project`, which would risk the
  leak-safe 404/403 invariant.
- Architectural invariants preserved: staff read the control-plane DB only (dual-DB
  rule); the credential vault stays write-only (ADR-0053) — staff cannot read a
  tenant's target secrets, even while impersonating; every future staff mutation is
  audit-logged.
