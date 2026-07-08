"""Staff-RBAC enforcement at the API boundary (ADR-0068).

The instance-level analogue of ``app.api.authz``: one path every admin-console
endpoint funnels through. Unlike org authz there is no per-tenant resource to resolve
— a staff role is an attribute of the user — so the check is pure and DB-free. An
authenticated non-staff user gets 403 (an authorization failure, not a hidden
per-tenant resource — the convention ADR-0035 chose); a staff member whose role lacks
the permission also gets 403.

This is deliberately a SEPARATE path from ``authorize_org``/``authorize_project`` —
never a short-circuit bolted into them — so the tenant-scoped 404/403 leak-safe
invariant is never weakened by an operator bypass.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import HTTPException

from app.api.deps import CurrentUser
from app.core.staff_permissions import StaffPermission, staff_role_can
from app.models.user import User


def authorize_staff(user: User, permission: StaffPermission) -> User:
    """Return ``user`` iff their staff role permits ``permission`` (ADR-0068).

    403 if the user is not staff (``staff_role`` is NULL); 403 if they are staff but
    the role does not grant the permission.
    """
    role = user.staff_role
    if role is None:
        raise HTTPException(status_code=403, detail="staff access required")
    if not staff_role_can(role, permission):
        raise HTTPException(status_code=403, detail="insufficient staff permissions")
    return user


def require_staff(permission: StaffPermission) -> Callable[..., Awaitable[User]]:
    """A FastAPI dependency gating a route on a specific staff permission.

    Usage: ``user: Annotated[User, Depends(require_staff(StaffPermission.X))]``.
    """

    async def _dependency(user: CurrentUser) -> User:
        return authorize_staff(user, permission)

    return _dependency
