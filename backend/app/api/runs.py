"""Run + findings routes (TRD §4, ADR-0026).

POST enqueues an autonomous (mode_b) or authoring (mode_c) run as a background
job and returns the job handle as ``run_id``; status + the ranked findings are
polled. Findings are read through the reused reporting ranking.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import Finding
from app.reporting import rank_findings
from app.repositories.finding_repository import FindingRepository
from app.repositories.project_repository import ProjectRepository

from .deps import get_jobs, get_run_executor, get_session
from .jobs import JobKind, JobRegistry, run_run_job
from .ports import RunExecutor, to_run_request
from .schemas import (
    FindingResponse,
    FindingsResponse,
    RunCreate,
    RunResponse,
    RunStatusResponse,
)

router = APIRouter(prefix="/api/v1", tags=["runs"])


def _finding_response(finding: Finding) -> FindingResponse:
    return FindingResponse(
        id=finding.id,
        root_cause_key=finding.root_cause_key,
        title=finding.title,
        layer=finding.layer.value,
        severity=finding.severity,
        status=finding.status,
        oracle_source=finding.oracle_source.value,
        explains_count=finding.explains_count,
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
    items = [_finding_response(f) for f in ranked]
    return FindingsResponse(run_id=run_id, count=len(items), findings=items)
