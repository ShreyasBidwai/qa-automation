"""Self-healing routes (B8, ADR-0040) — project-scoped, RBAC-gated, additive.

A run's heals are discovered by a post-run scan and reviewed by a human:

  - ``POST /runs/{id}/heal-scan`` — classify the run's newly-failing tests and
    propose addressing heals (RUN); returns the honest summary.
  - ``GET /heals`` / ``GET /runs/{id}/heals`` — the review queue / a run's heals
    (VIEW).
  - ``POST /heals/{id}/confirm`` | ``/reject`` — apply or discard a proposed heal
    (MANAGE_PROJECT). Confirming raises trust and re-addresses the live test;
    rejecting leaves it untouched.

These are NEW endpoints — no existing run/finding response shape changes (B8 is
additive while the UI is rebuilt in parallel).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.healing.service import HealService
from app.models.test_heal import STATUS_CONFIRMED, TestHeal
from app.repositories.test_heal_repository import TestHealRepository

from .authz import authorize_project
from .deps import CurrentUser, get_session
from .schemas import HealListResponse, HealResponse, HealScanResponse

router = APIRouter(prefix="/api/v1", tags=["healing"])


def _heal_response(heal: TestHeal) -> HealResponse:
    return HealResponse(
        id=heal.id,
        run_id=heal.run_id,
        test_case_id=heal.test_case_id,
        kind=heal.kind,
        failure_class=heal.failure_class,
        before_addr=heal.before_addr,
        after_addr=heal.after_addr,
        rationale=heal.rationale,
        confidence=heal.confidence,
        status=heal.status,
        trusted=heal.status == STATUS_CONFIRMED,
        created_at=heal.created_at,
    )


@router.post(
    "/projects/{project_id}/runs/{run_id}/heal-scan",
    response_model=HealScanResponse,
)
async def scan_run_for_heals(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HealScanResponse:
    """Classify the run's newly-failing tests; propose heals for location failures."""
    await authorize_project(session, project_id, current_user, Permission.RUN)
    report = await HealService(session).scan_run(project_id, run_id)
    return HealScanResponse(
        run_id=run_id,
        healed=len(report.healed),
        real_findings=len(report.real_findings),
        unhealed=len(report.unhealed),
        items=[_heal_response(h) for h in report.healed],
    )


@router.get("/projects/{project_id}/heals", response_model=HealListResponse)
async def list_proposed_heals(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HealListResponse:
    """The review queue: heals awaiting a human decision (lower-trust)."""
    await authorize_project(session, project_id, current_user, Permission.VIEW)
    heals = await TestHealRepository(session).list_proposed(project_id)
    items = [_heal_response(h) for h in heals]
    return HealListResponse(items=items, total=len(items))


@router.get(
    "/projects/{project_id}/runs/{run_id}/heals", response_model=HealListResponse
)
async def list_run_heals(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HealListResponse:
    await authorize_project(session, project_id, current_user, Permission.VIEW)
    heals = await TestHealRepository(session).list_for_run(project_id, run_id)
    items = [_heal_response(h) for h in heals]
    return HealListResponse(items=items, total=len(items))


@router.post(
    "/projects/{project_id}/heals/{heal_id}/confirm", response_model=HealResponse
)
async def confirm_heal(
    project_id: uuid.UUID,
    heal_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HealResponse:
    """Apply a proposed heal to the live test and restore trust (MANAGE_PROJECT)."""
    await authorize_project(
        session, project_id, current_user, Permission.MANAGE_PROJECT
    )
    heal = await HealService(session).confirm_heal(
        project_id, heal_id, resolved_by=current_user.email
    )
    if heal is None:
        raise HTTPException(status_code=404, detail="heal not found")
    return _heal_response(heal)


@router.post(
    "/projects/{project_id}/heals/{heal_id}/reject", response_model=HealResponse
)
async def reject_heal(
    project_id: uuid.UUID,
    heal_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HealResponse:
    """Discard a proposed heal; the live test is left untouched (MANAGE_PROJECT)."""
    await authorize_project(
        session, project_id, current_user, Permission.MANAGE_PROJECT
    )
    heal = await HealService(session).reject_heal(
        project_id, heal_id, resolved_by=current_user.email
    )
    if heal is None:
        raise HTTPException(status_code=404, detail="heal not found")
    return _heal_response(heal)
