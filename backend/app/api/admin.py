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
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_permissions import StaffPermission, staff_role_can
from app.models.enums import StaffRole
from app.models.job import Job
from app.models.staff_audit_log import StaffAuditLog
from app.models.user import User
from app.reporting.org_usage import OrgUsageReader
from app.repositories.admin_org_repository import AdminOrgRepository
from app.repositories.admin_user_repository import AdminUserRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.staff_audit_repository import StaffAuditRepository
from app.services.job_queue import JobQueue

from .deps import get_session
from .schemas import (
    AdminMeResponse,
    AdminModelCostItem,
    AdminOrgDetailResponse,
    AdminOrgListItem,
    AdminOrgListResponse,
    AdminOrgMemberItem,
    AdminOrgUsageResponse,
    AdminUserDetailResponse,
    AdminUserListItem,
    AdminUserListResponse,
    AdminUserOrgItem,
    JobSummary,
    SetStaffRoleRequest,
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


@router.get("/orgs/{org_id}/usage", response_model=AdminOrgUsageResponse)
async def org_usage(
    org_id: uuid.UUID,
    staff: Annotated[User, Depends(require_staff(StaffPermission.VIEW_BILLING))],
    session: Annotated[AsyncSession, Depends(get_session)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> AdminOrgUsageResponse:
    """Per-org AI cost + usage over the last ``days`` — the cost-to-serve basis for
    billing + margin (ADR-0069). VIEW_BILLING; the cost is the real billed spend we
    already capture per run (ADR-0049)."""
    since = datetime.now(UTC) - timedelta(days=days)
    summary = await OrgUsageReader(session).summary(org_id, since=since)
    return AdminOrgUsageResponse(
        org_id=org_id,
        since_days=days,
        total_cost_usd=float(summary.total_cost_usd),
        invocation_count=summary.invocation_count,
        run_count=summary.run_count,
        input_tokens=summary.input_tokens,
        output_tokens=summary.output_tokens,
        by_model=[
            AdminModelCostItem(
                model=item.model,
                invocation_count=item.invocation_count,
                total_cost_usd=float(item.total_cost_usd),
            )
            for item in summary.by_model
        ],
    )


# --- Users ------------------------------------------------------------------


async def _user_detail(
    session: AsyncSession, user_id: uuid.UUID
) -> AdminUserDetailResponse:
    result = await AdminUserRepository(session).get_with_orgs(user_id)
    if result is None:
        raise HTTPException(status_code=404, detail="user not found")
    user, orgs = result
    return AdminUserDetailResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        is_active=user.is_active,
        staff_role=user.staff_role.value if user.staff_role else None,
        created_at=user.created_at,
        orgs=[
            AdminUserOrgItem(org_id=org.id, org_name=org.name, role=role.value)
            for org, role in orgs
        ],
    )


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    staff: Annotated[User, Depends(require_staff(StaffPermission.VIEW_USERS))],
    session: Annotated[AsyncSession, Depends(get_session)],
    search: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminUserListResponse:
    """All users, newest-first, each with an org-membership count (VIEW_USERS)."""
    repo = AdminUserRepository(session)
    rows = await repo.list_users(search=search, limit=limit, offset=offset)
    total = await repo.count_users(search=search)
    return AdminUserListResponse(
        items=[
            AdminUserListItem(
                id=user.id,
                email=user.email,
                name=user.name,
                is_active=user.is_active,
                staff_role=user.staff_role.value if user.staff_role else None,
                org_count=org_count,
                created_at=user.created_at,
            )
            for user, org_count in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/users/{user_id}", response_model=AdminUserDetailResponse)
async def get_user(
    user_id: uuid.UUID,
    staff: Annotated[User, Depends(require_staff(StaffPermission.VIEW_USERS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminUserDetailResponse:
    """One user with their org memberships + roles (VIEW_USERS; 404 if absent)."""
    return await _user_detail(session, user_id)


@router.post("/users/{user_id}/deactivate", response_model=AdminUserDetailResponse)
async def deactivate_user(
    user_id: uuid.UUID,
    staff: Annotated[User, Depends(require_staff(StaffPermission.MANAGE_USERS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminUserDetailResponse:
    """Deactivate an account (blocks login; ADR-0030 auth check). MANAGE_USERS;
    a staff member cannot deactivate their own account. Audited (user.deactivate)."""
    if user_id == staff.id:
        raise HTTPException(
            status_code=400, detail="cannot deactivate your own account"
        )
    user = await AdminUserRepository(session).set_active(user_id, active=False)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    await StaffAuditRepository(session).record(
        actor=staff,
        action="user.deactivate",
        target_type="user",
        target_id=str(user_id),
        detail={"email": user.email},
    )
    return await _user_detail(session, user_id)


@router.post("/users/{user_id}/reactivate", response_model=AdminUserDetailResponse)
async def reactivate_user(
    user_id: uuid.UUID,
    staff: Annotated[User, Depends(require_staff(StaffPermission.MANAGE_USERS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminUserDetailResponse:
    """Restore a deactivated account. MANAGE_USERS; audited (user.reactivate)."""
    user = await AdminUserRepository(session).set_active(user_id, active=True)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    await StaffAuditRepository(session).record(
        actor=staff,
        action="user.reactivate",
        target_type="user",
        target_id=str(user_id),
        detail={"email": user.email},
    )
    return await _user_detail(session, user_id)


@router.post("/users/{user_id}/staff-role", response_model=AdminUserDetailResponse)
async def set_user_staff_role(
    user_id: uuid.UUID,
    body: SetStaffRoleRequest,
    staff: Annotated[User, Depends(require_staff(StaffPermission.MANAGE_USERS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminUserDetailResponse:
    """Grant (a role name) or revoke (null) a user's staff role — the in-band successor
    to the out-of-band ``is_operator`` flip (ADR-0068). MANAGE_USERS (superadmin only);
    a staff member cannot change their own role (no self-escalation / self-lockout).
    The role name is validated against the StaffRole allow-list. Audited."""
    if user_id == staff.id:
        raise HTTPException(status_code=400, detail="cannot change your own staff role")
    role: StaffRole | None = None
    if body.staff_role is not None:
        try:
            role = StaffRole(body.staff_role)
        except ValueError:
            raise HTTPException(status_code=422, detail="invalid staff_role") from None
    user = await AdminUserRepository(session).set_staff_role(user_id, role=role)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    await StaffAuditRepository(session).record(
        actor=staff,
        action="staff_role.set",
        target_type="user",
        target_id=str(user_id),
        detail={"email": user.email, "staff_role": role.value if role else None},
    )
    return await _user_detail(session, user_id)


# --- Jobs (queue recovery) --------------------------------------------------


def _job_summary(job: Job) -> JobSummary:
    return JobSummary(
        id=job.id,
        kind=job.kind.value,
        status=job.status.value,
        project_id=job.project_id,
        mode=job.mode,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        detail=job.detail,
        created_at=job.created_at,
        locked_at=job.locked_at,
        finished_at=job.finished_at,
    )


@router.post("/jobs/{job_id}/cancel", response_model=JobSummary)
async def cancel_job(
    job_id: uuid.UUID,
    staff: Annotated[User, Depends(require_staff(StaffPermission.MANAGE_JOBS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JobSummary:
    """Cancel a queued/running job (cross-tenant). MANAGE_JOBS; audited (job.cancel).
    404 if the job is absent, 409 if it is already terminal."""
    queue = JobQueue(session)
    job = await queue.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if not await queue.cancel(job_id):
        raise HTTPException(status_code=409, detail="job is not active")
    await StaffAuditRepository(session).record(
        actor=staff,
        action="job.cancel",
        target_type="job",
        target_id=str(job_id),
        detail={"kind": job.kind.value},
    )
    # cancel() set finished_at = func.now() (a SQL expression); reload the
    # server-evaluated value before serializing, or reading it would lazy-load.
    await session.refresh(job)
    return _job_summary(job)


@router.post("/jobs/{job_id}/requeue", response_model=JobSummary)
async def requeue_job(
    job_id: uuid.UUID,
    staff: Annotated[User, Depends(require_staff(StaffPermission.MANAGE_JOBS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JobSummary:
    """Re-run a failed/cancelled job by minting a FRESH job (new id → fresh run id,
    ADR-0036/0067). MANAGE_JOBS; audited (job.requeue). 404 if absent, 409 if the job
    is not in a requeuable state. Returns the NEW job."""
    queue = JobQueue(session)
    src = await queue.get(job_id)
    if src is None:
        raise HTTPException(status_code=404, detail="job not found")
    new_job = await queue.requeue(job_id)
    if new_job is None:
        raise HTTPException(
            status_code=409, detail="only a failed or cancelled job can be requeued"
        )
    await StaffAuditRepository(session).record(
        actor=staff,
        action="job.requeue",
        target_type="job",
        target_id=str(job_id),
        detail={"kind": src.kind.value, "new_job_id": str(new_job.id)},
    )
    # Reload server-default columns (created_at/available_at) before serializing.
    await session.refresh(new_job)
    return _job_summary(new_job)
