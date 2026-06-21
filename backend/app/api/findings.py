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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TriageStatus
from app.models.finding import Finding
from app.reporting import FindingDetail, FindingDetailReader, OpenFinding
from app.reporting.open_findings import OpenFindingsReader
from app.repositories.finding_triage_repository import FindingTriageRepository
from app.repositories.project_repository import ProjectRepository

from .deps import get_session
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
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OpenFindingsResponse:
    """The global findings inbox: what is currently broken across all projects."""
    page, total = await OpenFindingsReader(session).open_findings(
        None, limit=limit, offset=offset
    )
    return OpenFindingsResponse(
        items=await _enrich(session, page), total=total, limit=limit, offset=offset
    )


@router.get("/projects/{project_id}/findings", response_model=OpenFindingsResponse)
async def list_project_open_findings(
    project_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OpenFindingsResponse:
    """The currently-open findings for one project (404 if unknown/deleted)."""
    if await ProjectRepository(session).get(project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    page, total = await OpenFindingsReader(session).open_findings(
        project_id, limit=limit, offset=offset
    )
    return OpenFindingsResponse(
        items=await _enrich(session, page), total=total, limit=limit, offset=offset
    )


@router.post("/findings/triage", response_model=BulkTriageResponse)
async def bulk_triage(
    body: BulkTriageRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BulkTriageResponse:
    """Apply one disposition to many findings (ADR-0027/0028). Bad status → 422.

    Partial failure: ids that don't exist are reported in ``not_found`` while the
    valid ones are still triaged (200). Findings are resolved to their
    ``(project_id, root_cause_key)`` and deduped, so N ids touching one issue is a
    single upsert.
    """
    rows = (
        await session.execute(
            select(Finding.id, Finding.project_id, Finding.root_cause_key).where(
                Finding.id.in_(body.finding_ids)
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
