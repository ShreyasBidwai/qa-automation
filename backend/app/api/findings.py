"""Findings inbox + bulk triage (Sprint B1, ADR-0028).

``GET /findings`` (global) and ``GET /projects/{id}/findings`` return the
currently-open findings (latest run per project, muted/resolved excluded, ranked)
in the same shape as the run dashboard. ``POST /findings/triage`` applies one
disposition to many findings at once (the inbox bulk action), reusing the
per-finding triage upsert (ADR-0027).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TriageStatus
from app.models.finding import Finding
from app.models.project import Project
from app.reporting import FindingDetail, FindingDetailReader, OpenFinding
from app.reporting.open_findings import OpenFindingsReader
from app.repositories.finding_triage_repository import FindingTriageRepository
from app.repositories.project_repository import ProjectRepository

from .deps import CurrentUser, get_session
from .finding_view import build_finding_response
from .schemas import (
    BulkTriageRequest,
    BulkTriageResponse,
    FindingResponse,
    OpenFindingsResponse,
)

router = APIRouter(prefix="/api/v1", tags=["findings"])


async def _enrich(
    session: AsyncSession, page: list[OpenFinding]
) -> list[FindingResponse]:
    """Turn open findings into the run-dashboard shape, batched per (project, run).

    A single project's inbox is one group → one batched ``detail_for`` (no N+1);
    the global inbox groups the page by project (bounded by the page size).
    """
    if not page:
        return []
    reader = FindingDetailReader(session)
    groups: dict[tuple[uuid.UUID, uuid.UUID], list[Finding]] = {}
    for item in page:
        groups.setdefault((item.finding.project_id, item.finding.run_id), []).append(
            item.finding
        )

    detail: dict[uuid.UUID, FindingDetail] = {}
    for (project_id, run_id), findings in groups.items():
        detail.update(await reader.detail_for(project_id, run_id, findings))

    return [
        build_finding_response(item.finding, detail[item.finding.id], item.triage)
        for item in page
    ]


@router.get("/findings", response_model=OpenFindingsResponse)
async def list_open_findings(
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OpenFindingsResponse:
    """The global inbox: what's broken across the user's accessible projects."""
    page, total = await OpenFindingsReader(session).open_findings(
        None, limit=limit, offset=offset, accessor_id=current_user.id
    )
    return OpenFindingsResponse(
        items=await _enrich(session, page), total=total, limit=limit, offset=offset
    )


@router.get("/projects/{project_id}/findings", response_model=OpenFindingsResponse)
async def list_project_open_findings(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OpenFindingsResponse:
    """The currently-open findings for one project (404 if unknown/inaccessible)."""
    if await ProjectRepository(session).get(project_id, current_user.id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    page, total = await OpenFindingsReader(session).open_findings(
        project_id, limit=limit, offset=offset, accessor_id=current_user.id
    )
    return OpenFindingsResponse(
        items=await _enrich(session, page), total=total, limit=limit, offset=offset
    )


@router.post("/findings/triage", response_model=BulkTriageResponse)
async def bulk_triage(
    body: BulkTriageRequest,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BulkTriageResponse:
    """Apply one disposition to many findings (ADR-0027/0028). Bad status → 422.

    Partial failure: ids that don't exist *or aren't in an accessible project*
    (ADR-0031) are reported in ``not_found`` while the valid ones are still triaged
    (200). Findings are resolved to their ``(project_id, root_cause_key)`` and
    deduped, so N ids touching one issue is a single upsert.
    """
    rows = (
        await session.execute(
            select(Finding.id, Finding.project_id, Finding.root_cause_key)
            .join(Project, Project.id == Finding.project_id)
            .where(
                Finding.id.in_(body.finding_ids),
                Project.deleted_at.is_(None),
                or_(
                    Project.owner_id.is_(None),
                    Project.owner_id == current_user.id,
                ),
            )
        )
    ).all()

    found_ids = {row[0] for row in rows}
    not_found = sorted(set(body.finding_ids) - found_ids)

    status = TriageStatus(body.status)
    triage_repo = FindingTriageRepository(session)
    # Dedupe to distinct (project_id, root_cause_key) issues — N ids on one issue
    # is one upsert (ADR-0027).
    for project_id, root_cause_key in {(row[1], row[2]) for row in rows}:
        await triage_repo.upsert(
            project_id, root_cause_key, status=status, note=body.note
        )

    return BulkTriageResponse(
        status=body.status,
        requested=len(body.finding_ids),
        updated=sorted(found_ids),
        not_found=not_found,
    )
