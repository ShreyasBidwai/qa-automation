"""The staff (platform-operator) permission matrix (ADR-0068).

The instance-level analogue of ``app.core.permissions``: a cross-tenant staff role
maps to the set of admin-console actions it may perform, and ``staff_role_can``
answers "may this staff role do this?". Pure data + one predicate — no DB, no HTTP.
Distinct from org RBAC (owner/admin/member/viewer), which is tenant-scoped; these
gate the operator console that spans every tenant.
"""

from __future__ import annotations

import enum

from app.models.enums import StaffRole


class StaffPermission(str, enum.Enum):
    """A cross-tenant admin action gated by staff RBAC (ADR-0068)."""

    VIEW_OPS = "view_ops"  # read queue / jobs / incidents (all tenants)
    MANAGE_JOBS = "manage_jobs"  # retry / cancel a job
    VIEW_TENANTS = "view_tenants"  # list / inspect organizations
    MANAGE_TENANTS = "manage_tenants"  # suspend / reactivate an org
    VIEW_USERS = "view_users"  # list / inspect users
    MANAGE_USERS = "manage_users"  # (de)activate; grant / revoke staff roles
    VIEW_BILLING = "view_billing"  # read plans / usage / spend
    MANAGE_BILLING = "manage_billing"  # assign plan, credits, refunds
    VIEW_AUDIT = "view_audit"  # read the staff audit log
    IMPERSONATE = "impersonate"  # assume a tenant user (time-boxed, audited)


# The read-only visibility every staff role shares — mutate nothing.
_READ_ONLY: frozenset[StaffPermission] = frozenset(
    {
        StaffPermission.VIEW_OPS,
        StaffPermission.VIEW_TENANTS,
        StaffPermission.VIEW_USERS,
        StaffPermission.VIEW_BILLING,
        StaffPermission.VIEW_AUDIT,
    }
)

# Role → allowed permissions (ADR-0068). ``superadmin`` is a superset; the rest are
# least-privilege slices around the shared read-only base (separation of duties:
# support acts on jobs + impersonates but never touches money; billing owns billing
# but not jobs/impersonation; read_only_ops mutates nothing).
_MATRIX: dict[StaffRole, frozenset[StaffPermission]] = {
    StaffRole.SUPERADMIN: frozenset(StaffPermission),
    StaffRole.SUPPORT: _READ_ONLY
    | {StaffPermission.MANAGE_JOBS, StaffPermission.IMPERSONATE},
    StaffRole.BILLING: _READ_ONLY | {StaffPermission.MANAGE_BILLING},
    StaffRole.READ_ONLY_OPS: _READ_ONLY,
}


def staff_role_can(role: StaffRole, permission: StaffPermission) -> bool:
    """True iff staff ``role`` is permitted to perform ``permission`` (ADR-0068)."""
    return permission in _MATRIX[role]
