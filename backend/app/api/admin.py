"""The platform operator/admin console API (ADR-0068).

Cross-tenant, staff-only. Every route gates on a specific ``StaffPermission`` via
``require_staff`` (app.api.staff_authz) — a SEPARATE authorization lane from the
tenant-scoped org RBAC, never a bypass of it. Read routes take the least-privilege
permission; mutations (added incrementally) each take their own and append a
``staff_audit_log`` entry. Reads touch the control-plane DB only (dual-DB rule) and
never surface a tenant's target secrets (the vault stays write-only, ADR-0053).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_permissions import StaffPermission, staff_role_can
from app.models.staff_audit_log import StaffAuditLog
from app.models.user import User
from app.repositories.staff_audit_repository import StaffAuditRepository

from .deps import get_session
from .schemas import AdminMeResponse, StaffAuditItem, StaffAuditListResponse
from .staff_authz import require_staff

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _permissions_for(user: User) -> list[str]:
    """The sorted action values the user's staff role grants (empty if not staff)."""
    role = user.staff_role
    if role is None:
        return []
    return sorted(p.value for p in StaffPermission if staff_role_can(role, p))


@router.get("/me", response_model=AdminMeResponse)
async def admin_me(
    user: Annotated[User, Depends(require_staff(StaffPermission.VIEW_OPS))],
) -> AdminMeResponse:
    """The signed-in staff member's console identity + granted actions (ADR-0068).

    403 for a non-staff user; the least-privileged ``read_only_ops`` passes. The UI
    reads ``permissions`` to decide which admin surfaces to show.
    """
    assert user.staff_role is not None  # require_staff guarantees a staff role
    return AdminMeResponse(
        user_id=user.id,
        email=user.email,
        staff_role=user.staff_role.value,
        permissions=_permissions_for(user),
    )


def _audit_item(entry: StaffAuditLog) -> StaffAuditItem:
    return StaffAuditItem(
        id=entry.id,
        created_at=entry.created_at,
        actor_id=entry.actor_id,
        actor_email=entry.actor_email,
        action=entry.action,
        target_type=entry.target_type,
        target_id=entry.target_id,
        detail=entry.detail,
    )


@router.get("/audit", response_model=StaffAuditListResponse)
async def list_audit(
    user: Annotated[User, Depends(require_staff(StaffPermission.VIEW_AUDIT))],
    session: Annotated[AsyncSession, Depends(get_session)],
    action: Annotated[str | None, Query()] = None,
    actor_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> StaffAuditListResponse:
    """The staff audit trail, newest-first (VIEW_AUDIT; 403 otherwise)."""
    repo = StaffAuditRepository(session)
    entries = await repo.list(
        action=action, actor_id=actor_id, limit=limit, offset=offset
    )
    total = await repo.count(action=action, actor_id=actor_id)
    return StaffAuditListResponse(
        items=[_audit_item(entry) for entry in entries],
        total=total,
        limit=limit,
        offset=offset,
    )
