"""Account dashboard — the post-login account overview (ADR-0065).

``GET /account/dashboard`` aggregates health across every project the caller's orgs
own: current headline health + open-findings severity + per-project health, and a
range-scoped pass-rate/outcome trend and recent activity. Org-scoped (a user only ever
sees their own orgs' projects) and composed from the existing batched readers, so it is
a fixed number of grouped queries regardless of account size.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.reporting.account_dashboard import AccountDashboard, AccountDashboardReader
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository

from .deps import CurrentUser, get_session
from .schemas import (
    AccountDashboardResponse,
    ProjectHealthItem,
    RecentRunItem,
    TrendPointItem,
)

router = APIRouter(prefix="/api/v1", tags=["account"])

# The projects page is bounded; the dashboard reads the whole account, so cap the
# project fan-in (the reader caps it too — belt and suspenders).
_MAX_PROJECTS = 500


@router.get("/account/dashboard", response_model=AccountDashboardResponse)
async def account_dashboard(
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    range_days: Annotated[int, Query(ge=1, le=3650)] = 30,
) -> AccountDashboardResponse:
    """Account-wide health + a ``range_days`` trend. Org-scoped: only the caller's own
    orgs' projects are aggregated (no cross-tenant read)."""
    org_ids = await OrganizationRepository(session).member_org_ids(current_user.id)
    projects = await ProjectRepository(session).list(
        limit=_MAX_PROJECTS, offset=0, org_ids=org_ids
    )
    names = {project.id: project.name for project in projects}
    dashboard = await AccountDashboardReader(session).build(
        names, range_days=range_days
    )
    return _to_response(dashboard)


def _to_response(d: AccountDashboard) -> AccountDashboardResponse:
    return AccountDashboardResponse(
        range_days=d.range_days,
        projects_total=d.projects_total,
        projects_by_status=d.projects_by_status,
        open_findings=d.open_findings,
        project_health=[
            ProjectHealthItem(
                project_id=row.project_id,
                name=row.name,
                status=row.status,
                pass_rate=row.pass_rate,
                open_findings=row.open_findings,
                last_run_at=row.last_run_at,
            )
            for row in d.project_health
        ],
        runs_total=d.runs_total,
        tests_total=d.tests_total,
        outcomes=d.outcomes,
        pass_rate=d.pass_rate,
        trend=[
            TrendPointItem(
                date=point.date,
                runs=point.runs,
                passed=point.passed,
                failed=point.failed,
                errored=point.errored,
                skipped=point.skipped,
                pass_rate=point.pass_rate,
            )
            for point in d.trend
        ],
        recent_runs=[
            RecentRunItem(
                run_id=run.run_id,
                project_id=run.project_id,
                project_name=run.project_name,
                mode=run.mode,
                status=run.status,
                pass_rate=run.pass_rate,
                created_at=run.created_at,
            )
            for run in d.recent_runs
        ],
    )
