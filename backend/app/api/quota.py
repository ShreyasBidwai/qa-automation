"""Enqueue-time gate: may this org start work? (ADR-0068 suspension + ADR-0069 quota).

The single choke point where a suspended tenant is blocked and a plan's monthly
run-credit allowance is enforced — the durable queue is where "may this org run?" is
answerable, so both run + ingest creation funnel through here. Kept out of ``authz.py``
(pure RBAC) and out of ``JobQueue`` (pure mechanics). Raises ``HTTPException`` so it
reads inline in a route body, right after ``authorize_project``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobKind
from app.models.job import Job
from app.models.organization import Organization
from app.models.project import Project
from app.repositories.plan_repository import PlanRepository


async def enforce_org_not_suspended(session: AsyncSession, org_id: uuid.UUID) -> None:
    """403 if the org is suspended (ADR-0068). A suspended tenant keeps read access but
    starts no new work."""
    org = await session.get(Organization, org_id)
    if org is not None and org.is_suspended:
        raise HTTPException(status_code=403, detail="organization is suspended")


async def _runs_this_calendar_month(session: AsyncSession, org_id: uuid.UUID) -> int:
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count())
        .select_from(Job)
        .join(Project, Project.id == Job.project_id)
        .where(
            Job.kind == JobKind.RUN,
            Project.org_id == org_id,
            Job.created_at >= start,
        )
    )
    return int(await session.scalar(stmt) or 0)


async def enforce_org_can_run(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Gate a RUN enqueue: block a suspended org (403), then enforce the plan's monthly
    run-credit allowance (402 when exhausted). A NULL allowance means unlimited
    (ADR-0069). One run currently costs one credit — cost-∝-credit refinement is a later
    slice (the real per-run cost we already capture, ADR-0049, will size the debit)."""
    org = await session.get(Organization, org_id)
    if org is None:
        return
    if org.is_suspended:
        raise HTTPException(status_code=403, detail="organization is suspended")
    plan = await PlanRepository(session).effective_for(org.plan_key)
    if plan is None or plan.included_run_credits_monthly is None:
        return  # unseeded catalog, or an unlimited (enterprise) plan
    used = await _runs_this_calendar_month(session, org_id)
    if used >= plan.included_run_credits_monthly:
        raise HTTPException(
            status_code=402, detail="monthly run limit reached for this plan"
        )
