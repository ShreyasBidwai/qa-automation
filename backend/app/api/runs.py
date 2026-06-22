"""Run + findings routes (TRD §4, ADR-0026).

POST enqueues an autonomous (mode_b) or authoring (mode_c) run as a background
job and returns the job handle as ``run_id``; status + the ranked findings are
polled. Findings are read through the reused reporting ranking.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.models.enums import JobKind, Outcome, TriageStatus
from app.models.job import Job
from app.models.user import User
from app.reporting import FindingDetailReader, rank_findings
from app.reporting.heal_reconciliation import superseded_finding_ids
from app.repositories.finding_repository import FindingRepository
from app.repositories.finding_triage_repository import FindingTriageRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.services.job_queue import JobQueue

from .authz import authorize_project
from .deps import CurrentUser, get_session
from .finding_view import build_finding_response
from .jobs import dispatch_job
from .ports import run_request_to_payload, to_run_request
from .schemas import (
    FindingResponse,
    FindingsResponse,
    RunCreate,
    RunListItem,
    RunListResponse,
    RunResponse,
    RunStatusResponse,
    TriagePatch,
)

router = APIRouter(prefix="/api/v1", tags=["runs"])


def _pass_rate(counts: dict[Outcome, int] | None) -> float | None:
    if not counts:
        return None
    total = sum(counts.values())
    if total == 0:
        return None
    return round(counts.get(Outcome.PASS, 0) / total, 4)


async def _authorized_run_job(
    run_id: uuid.UUID,
    *,
    session: AsyncSession,
    user: User,
    permission: Permission,
) -> Job:
    """Resolve a RUN job and RBAC-check its project (ADR-0033).

    404 for an unknown run OR a non-member of the project's org (existence not
    leaked); 403 if the caller is in the org but the role lacks ``permission``.
    """
    job = await JobQueue(session).get(run_id)
    if job is None or job.kind is not JobKind.RUN:
        raise HTTPException(status_code=404, detail="run not found")
    await authorize_project(session, job.project_id, user, permission)
    return job


@router.post("/projects/{project_id}/runs", status_code=202, response_model=RunResponse)
async def create_run(
    project_id: uuid.UUID,
    body: RunCreate,
    current_user: CurrentUser,
    request: Request,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunResponse:
    await authorize_project(session, project_id, current_user, Permission.RUN)
    run_request = to_run_request(body)
    # A run is non-idempotent (it persists a run + findings), so it gets a single
    # attempt — no auto-replay of partial side effects. The queue itself supports
    # retry-with-backoff (ADR-0034) for jobs that opt in.
    job = await JobQueue(session).enqueue(
        kind=JobKind.RUN,
        project_id=project_id,
        mode=body.mode,
        payload=run_request_to_payload(run_request),
        max_attempts=1,
    )
    # Commit now so the durable row is visible to whoever executes it.
    await session.commit()
    # Decoupled topology (B5, ADR-0036): only dispatch in-process if THIS node
    # carries an executor (single-box stub). The slim/control-plane backend has
    # none — the run stays queued for a toolchain-present runner worker to claim.
    executor = getattr(request.app.state, "run_executor", None)
    if executor is not None:
        background_tasks.add_task(
            dispatch_job,
            sessionmaker=request.app.state.sessionmaker,
            job_id=job.id,
            executor=executor,
        )
    return RunResponse(run_id=job.id, status=job.status.value)


@router.get("/projects/{project_id}/runs", response_model=RunListResponse)
async def list_project_runs(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunListResponse:
    await authorize_project(session, project_id, current_user, Permission.VIEW)
    run_repo = RunRepository(session)
    runs = await run_repo.list_for_project(project_id, limit=limit, offset=offset)
    counts = await ResultRepository(session).outcome_counts_for_runs(
        project_id, [run.id for run in runs]
    )
    items = [
        RunListItem(
            id=run.id,
            mode=run.mode.value,
            status=run.status,
            created_at=run.created_at,
            pass_rate=_pass_rate(counts.get(run.id)),
        )
        for run in runs
    ]
    return RunListResponse(
        items=items,
        total=await run_repo.count_for_project(project_id),
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}", response_model=RunStatusResponse)
async def get_run(
    run_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunStatusResponse:
    job = await _authorized_run_job(
        run_id,
        session=session,
        user=current_user,
        permission=Permission.VIEW,
    )
    return RunStatusResponse(
        run_id=job.id,
        mode=job.mode or "",
        status=job.status.value,
        summary=job.summary,
    )


@router.get("/runs/{run_id}/findings", response_model=FindingsResponse)
async def get_run_findings(
    run_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FindingsResponse:
    job = await _authorized_run_job(
        run_id,
        session=session,
        user=current_user,
        permission=Permission.VIEW,
    )
    if job.run_id is None:  # not executed yet, or an authoring (mode_c) run
        return FindingsResponse(run_id=run_id, count=0, findings=[])
    findings = await FindingRepository(session).list_for_run(job.project_id, job.run_id)
    ranked = rank_findings(findings)
    detail = await FindingDetailReader(session).detail_for(
        job.project_id, job.run_id, ranked
    )
    # Triage block merged in one batched lookup by root_cause_key (no N+1, ADR-0027).
    triage = await FindingTriageRepository(session).get_for_keys(
        job.project_id, [f.root_cause_key for f in ranked]
    )
    # The run dashboard shows every finding but TAGS heal-superseded ones (addressing
    # drift) rather than dropping them — the per-run view is non-lossy by design.
    superseded = await superseded_finding_ids(session, ranked)
    items = [
        build_finding_response(
            f,
            detail[f.id],
            triage.get(f.root_cause_key),
            superseded_by_heal=f.id in superseded,
        )
        for f in ranked
    ]
    return FindingsResponse(run_id=run_id, count=len(items), findings=items)


@router.patch("/runs/{run_id}/findings/{finding_id}", response_model=FindingResponse)
async def triage_finding(
    run_id: uuid.UUID,
    finding_id: uuid.UUID,
    body: TriagePatch,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FindingResponse:
    """Set a finding's triage disposition, keyed by its root_cause_key (ADR-0027).

    The disposition follows the logical issue, not this run's row, so a later run
    producing the same root_cause_key inherits it. Requires the TRIAGE permission
    (a viewer is denied → 403); bad status → 422 (schema); unknown finding → 404.
    """
    job = await _authorized_run_job(
        run_id,
        session=session,
        user=current_user,
        permission=Permission.TRIAGE,
    )
    if job.run_id is None:
        raise HTTPException(status_code=404, detail="run not found")
    finding = await FindingRepository(session).get(job.project_id, finding_id)
    if finding is None or finding.run_id != job.run_id:
        raise HTTPException(status_code=404, detail="finding not found")

    record = await FindingTriageRepository(session).upsert(
        job.project_id,
        finding.root_cause_key,
        status=TriageStatus(body.status),
        note=body.note,
    )
    detail = await FindingDetailReader(session).detail_for(
        job.project_id, job.run_id, [finding]
    )
    superseded = await superseded_finding_ids(session, [finding])
    return build_finding_response(
        finding,
        detail[finding.id],
        record,
        superseded_by_heal=finding.id in superseded,
    )
