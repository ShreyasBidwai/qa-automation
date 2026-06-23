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

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission, role_can
from app.models.enums import TriageStatus
from app.models.finding import Finding
from app.models.project import Project
from app.reporting import FindingDetail, FindingDetailReader, OpenFinding
from app.reporting.heal_reconciliation import superseded_finding_ids
from app.reporting.open_findings import OpenFindingsReader
from app.repositories.finding_triage_repository import FindingTriageRepository
from app.repositories.organization_repository import OrganizationRepository
from app.screenshots import get_screenshot

from .authz import authorize_project
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
        build_finding_response(
            item.finding,
            detail[item.finding.id],
            item.triage,
            superseded_by_heal=item.superseded,
        )
        for item in page
    ]


@router.get("/findings", response_model=OpenFindingsResponse)
async def list_open_findings(
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_superseded: Annotated[bool, Query()] = False,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
) -> OpenFindingsResponse:
    """The global inbox: what's broken across the user's viewable orgs (ADR-0033).

    Optional ``project_id`` narrows the inbox to one project SERVER-SIDE — the whole
    result set + total, not just the current page (ADR-0052). It still rides the
    caller's org scope, so a project the caller can't view simply yields nothing
    (existence not leaked). Heal-superseded findings (addressing drift) are excluded
    by default; pass ``include_superseded=true`` to see them tagged.
    """
    org_ids = await OrganizationRepository(session).member_org_ids(current_user.id)
    page, total = await OpenFindingsReader(session).open_findings(
        project_id,
        limit=limit,
        offset=offset,
        org_ids=org_ids,
        include_superseded=include_superseded,
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
    include_superseded: Annotated[bool, Query()] = False,
) -> OpenFindingsResponse:
    """The currently-open findings for one project (404 if unknown/inaccessible).

    Heal-superseded findings (addressing drift) are excluded by default; pass
    ``include_superseded=true`` to see them tagged.
    """
    await authorize_project(session, project_id, current_user, Permission.VIEW)
    page, total = await OpenFindingsReader(session).open_findings(
        project_id, limit=limit, offset=offset, include_superseded=include_superseded
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

    Partial failure: ids that don't exist *or are in a project the caller can't
    triage* (not a member, or a viewer — ADR-0033) are reported in ``not_found``
    while the valid ones are still triaged (200). Findings are resolved to their
    ``(project_id, root_cause_key)`` and deduped, so N ids touching one issue is a
    single upsert.
    """
    # The orgs where the caller's role permits TRIAGE (owner/admin/member).
    triage_org_ids = [
        org.id
        for org, role in await OrganizationRepository(session).list_orgs_for_user(
            current_user.id
        )
        if role_can(role, Permission.TRIAGE)
    ]
    rows = (
        await session.execute(
            select(Finding.id, Finding.project_id, Finding.root_cause_key)
            .join(Project, Project.id == Finding.project_id)
            .where(
                Finding.id.in_(body.finding_ids),
                Project.deleted_at.is_(None),
                Project.org_id.in_(triage_org_ids),
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


@router.get("/findings/{finding_id}", response_model=FindingResponse)
async def get_finding(
    finding_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FindingResponse:
    """The full single-finding payload for the single-issue view (ADR-0052).

    Reuses the run-dashboard builder (detail + triage + heal-supersede + the
    has_screenshot flag). Authorized VIEW on the finding's project; 404 if unknown or
    inaccessible (existence not leaked, ADR-0033) — the same pattern as the screenshot
    endpoint.
    """
    finding = (
        await session.scalars(select(Finding).where(Finding.id == finding_id))
    ).one_or_none()
    if finding is None:
        raise HTTPException(status_code=404, detail="finding not found")
    await authorize_project(session, finding.project_id, current_user, Permission.VIEW)
    detail = await FindingDetailReader(session).detail_for(
        finding.project_id, finding.run_id, [finding]
    )
    triage = await FindingTriageRepository(session).get_for_keys(
        finding.project_id, [finding.root_cause_key]
    )
    superseded = await superseded_finding_ids(session, [finding])
    return build_finding_response(
        finding,
        detail[finding.id],
        triage.get(finding.root_cause_key),
        superseded_by_heal=finding.id in superseded,
    )


@router.get("/findings/{finding_id}/screenshot")
async def get_finding_screenshot(
    finding_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Stream a finding's failure screenshot to an authorized caller (ADR-0051).

    Screenshots may hold sensitive app state, so they are NEVER served from a public
    path: the bytes are read through the single ``app.screenshots`` indirection and
    returned only after authorizing VIEW on the finding's project. 404 if the finding
    is unknown / inaccessible (existence not leaked, ADR-0033) or has no screenshot;
    403 if the caller is in the org but the role lacks VIEW.
    """
    finding = (
        await session.scalars(select(Finding).where(Finding.id == finding_id))
    ).one_or_none()
    if finding is None:
        raise HTTPException(status_code=404, detail="finding not found")
    # VIEW on the finding's project (404 for a non-member; 403 for in-org/no-perm).
    await authorize_project(session, finding.project_id, current_user, Permission.VIEW)
    if finding.screenshot_ref is None:
        raise HTTPException(status_code=404, detail="no screenshot for this finding")
    data = get_screenshot(finding.screenshot_ref)
    if data is None:  # ref recorded but bytes gone (e.g. ephemeral disk wiped)
        raise HTTPException(status_code=404, detail="screenshot not available")
    return Response(content=data, media_type="image/png")
