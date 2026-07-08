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

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_permissions import StaffPermission, staff_role_can
from app.models.staff_audit_log import StaffAuditLog
from app.models.user import User
from app.repositories.admin_org_repository import AdminOrgRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.staff_audit_repository import StaffAuditRepository

from .deps import get_session
from .schemas import (
    AdminMeResponse,
    AdminOrgDetailResponse,
    AdminOrgListItem,
    AdminOrgListResponse,
    AdminOrgMemberItem,
    StaffAuditItem,
    StaffAuditListResponse,
)
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


# --- Tenants (organizations) ------------------------------------------------


async def _org_detail(
    session: AsyncSession, org_id: uuid.UUID
) -> AdminOrgDetailResponse:
    """Build the drill-in view (counts + members); 404 if the org is gone."""
    result = await AdminOrgRepository(session).get_with_counts(org_id)
    if result is None:
        raise HTTPException(status_code=404, detail="organization not found")
    org, member_count, project_count = result
    members = await OrganizationRepository(session).list_members(org_id)
    return AdminOrgDetailResponse(
        id=org.id,
        name=org.name,
        is_personal=org.is_personal,
        suspended=org.is_suspended,
        member_count=member_count,
        project_count=project_count,
        created_at=org.created_at,
        members=[
            AdminOrgMemberItem(
                user_id=user.id,
                email=user.email,
                name=user.name,
                role=member.role.value,
            )
            for member, user in members
        ],
    )


@router.get("/orgs", response_model=AdminOrgListResponse)
async def list_orgs(
    staff: Annotated[User, Depends(require_staff(StaffPermission.VIEW_TENANTS))],
    session: Annotated[AsyncSession, Depends(get_session)],
    search: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminOrgListResponse:
    """All organizations, newest-first, with rollup counts (VIEW_TENANTS; else 403)."""
    repo = AdminOrgRepository(session)
    rows = await repo.list_orgs(search=search, limit=limit, offset=offset)
    total = await repo.count_orgs(search=search)
    return AdminOrgListResponse(
        items=[
            AdminOrgListItem(
                id=org.id,
                name=org.name,
                is_personal=org.is_personal,
                suspended=org.is_suspended,
                member_count=member_count,
                project_count=project_count,
                created_at=org.created_at,
            )
            for org, member_count, project_count in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/orgs/{org_id}", response_model=AdminOrgDetailResponse)
async def get_org(
    org_id: uuid.UUID,
    staff: Annotated[User, Depends(require_staff(StaffPermission.VIEW_TENANTS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminOrgDetailResponse:
    """One organization with members + counts (VIEW_TENANTS; 404 if absent)."""
    return await _org_detail(session, org_id)


async def _set_org_suspended(
    session: AsyncSession,
    actor: User,
    org_id: uuid.UUID,
    *,
    suspended: bool,
    action: str,
) -> AdminOrgDetailResponse:
    org = await AdminOrgRepository(session).set_suspended(org_id, suspended=suspended)
    if org is None:
        raise HTTPException(status_code=404, detail="organization not found")
    await StaffAuditRepository(session).record(
        actor=actor,
        action=action,
        target_type="org",
        target_id=str(org_id),
        detail={"name": org.name, "suspended": suspended},
    )
    return await _org_detail(session, org_id)


@router.post("/orgs/{org_id}/suspend", response_model=AdminOrgDetailResponse)
async def suspend_org(
    org_id: uuid.UUID,
    staff: Annotated[User, Depends(require_staff(StaffPermission.MANAGE_TENANTS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminOrgDetailResponse:
    """Suspend a tenant — members keep read access but can start no runs (enforced at
    the enqueue choke point, B3). MANAGE_TENANTS; audited (org.suspend)."""
    return await _set_org_suspended(
        session, staff, org_id, suspended=True, action="org.suspend"
    )


@router.post("/orgs/{org_id}/reactivate", response_model=AdminOrgDetailResponse)
async def reactivate_org(
    org_id: uuid.UUID,
    staff: Annotated[User, Depends(require_staff(StaffPermission.MANAGE_TENANTS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminOrgDetailResponse:
    """Lift a suspension. MANAGE_TENANTS; audited (org.reactivate)."""
    return await _set_org_suspended(
        session, staff, org_id, suspended=False, action="org.reactivate"
    )
