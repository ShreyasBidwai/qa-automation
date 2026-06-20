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

from app.models.enums import Outcome, TriageStatus
from app.models.finding import Finding
from app.models.finding_triage import FindingTriage
from app.reporting import FindingDetail, FindingDetailReader, rank_findings
from app.repositories.finding_repository import FindingRepository
from app.repositories.finding_triage_repository import FindingTriageRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository

from .deps import get_jobs, get_run_executor, get_session
from .jobs import JobKind, JobRegistry, run_run_job
from .ports import RunExecutor, to_run_request
from .schemas import (
    EvidenceItem,
    FindingHistory,
    FindingLocation,
    FindingResponse,
    FindingsResponse,
    RunCreate,
    RunListItem,
    RunListResponse,
    RunResponse,
    RunStatusResponse,
    TriageInfo,
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


def _triage_info(record: FindingTriage | None) -> TriageInfo:
    """The current disposition, or the open default when nothing is triaged."""
    if record is None:
        return TriageInfo(status=TriageStatus.OPEN.value)
    return TriageInfo(
        status=record.status.value, note=record.note, triaged_at=record.triaged_at
    )


def _finding_response(
    finding: Finding, detail: FindingDetail, triage: FindingTriage | None
) -> FindingResponse:
    return FindingResponse(
        id=finding.id,
        root_cause_key=finding.root_cause_key,
        title=finding.title,
        layer=finding.layer.value,
        severity=finding.severity,
        status=finding.status,
        oracle_source=finding.oracle_source.value,
        explains_count=finding.explains_count,
        confidence_mixed=finding.confidence_mixed,
        expected=dict(finding.expected),
        location=FindingLocation.model_validate(detail.location),
        evidence=[EvidenceItem.model_validate(item) for item in detail.evidence],
        history=FindingHistory.model_validate(detail.history),
        evidence_ref=finding.evidence_ref,
        triage=_triage_info(triage),
    )


@router.post("/projects/{project_id}/runs", status_code=202, response_model=RunResponse)
async def create_run(
    project_id: uuid.UUID,
    body: RunCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_session)],
    jobs: Annotated[JobRegistry, Depends(get_jobs)],
    executor: Annotated[RunExecutor, Depends(get_run_executor)],
) -> RunResponse:
    if await ProjectRepository(session).get(project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    run_request = to_run_request(body)
    job = jobs.create(kind=JobKind.RUN, project_id=project_id, mode=body.mode)
    background_tasks.add_task(
        run_run_job,
        sessionmaker=request.app.state.sessionmaker,
        jobs=jobs,
        job_id=job.id,
        project_id=project_id,
        executor=executor,
        request=run_request,
    )
    return RunResponse(run_id=job.id, status=job.status.value)


@router.get("/projects/{project_id}/runs", response_model=RunListResponse)
async def list_project_runs(
    project_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunListResponse:
    if await ProjectRepository(session).get(project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
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
    run_id: uuid.UUID, jobs: Annotated[JobRegistry, Depends(get_jobs)]
) -> RunStatusResponse:
    job = jobs.get(run_id)
    if job is None or job.kind is not JobKind.RUN:
        raise HTTPException(status_code=404, detail="run not found")
    return RunStatusResponse(
        run_id=job.id,
        mode=job.mode or "",
        status=job.status.value,
        summary=job.summary,
    )


@router.get("/runs/{run_id}/findings", response_model=FindingsResponse)
async def get_run_findings(
    run_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    jobs: Annotated[JobRegistry, Depends(get_jobs)],
) -> FindingsResponse:
    job = jobs.get(run_id)
    if job is None or job.kind is not JobKind.RUN:
        raise HTTPException(status_code=404, detail="run not found")
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
    items = [
        _finding_response(f, detail[f.id], triage.get(f.root_cause_key)) for f in ranked
    ]
    return FindingsResponse(run_id=run_id, count=len(items), findings=items)


@router.patch("/runs/{run_id}/findings/{finding_id}", response_model=FindingResponse)
async def triage_finding(
    run_id: uuid.UUID,
    finding_id: uuid.UUID,
    body: TriagePatch,
    session: Annotated[AsyncSession, Depends(get_session)],
    jobs: Annotated[JobRegistry, Depends(get_jobs)],
) -> FindingResponse:
    """Set a finding's triage disposition, keyed by its root_cause_key (ADR-0027).

    The disposition follows the logical issue, not this run's row, so a later run
    producing the same root_cause_key inherits it. Bad status → 422 (schema);
    unknown finding → 404.
    """
    job = jobs.get(run_id)
    if job is None or job.kind is not JobKind.RUN or job.run_id is None:
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
    return _finding_response(finding, detail[finding.id], record)
