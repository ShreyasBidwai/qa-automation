"""Project + ingest + job-status routes (TRD §4, ADR-0026).

Thin: validate, enforce tenancy, persist the project / enqueue background work.
The Brain build runs as an in-process background job; the client polls
``GET /jobs/{job_id}``.
"""

from __future__ import annotations

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.repositories.project_repository import ProjectRepository

from .deps import get_ingestor, get_jobs, get_session
from .jobs import JobKind, JobRegistry, run_ingest_job
from .ports import Ingestor
from .schemas import (
    IngestResponse,
    JobStatusResponse,
    ProjectCreate,
    ProjectResponse,
)

router = APIRouter(prefix="/api/v1", tags=["projects"])


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"
    return f"{base}-{uuid.uuid4().hex[:8]}"  # unique suffix avoids collisions


def _project_response(project: Project) -> ProjectResponse:
    settings = project.settings
    return ProjectResponse(
        id=project.id,
        name=project.name,
        slug=project.slug,
        repo_url=str(settings.get("repo_url", "")),
        app_url=settings.get("app_url"),
        auth_config_ref=settings.get("auth_config_ref"),
        created_at=project.created_at,
    )


@router.post("/projects", status_code=201, response_model=ProjectResponse)
async def create_project(
    body: ProjectCreate, session: Annotated[AsyncSession, Depends(get_session)]
) -> ProjectResponse:
    project = Project(
        name=body.name,
        slug=_slug(body.name),
        settings={
            "repo_url": body.repo_url,
            "app_url": body.app_url,
            "auth_config_ref": body.auth_config_ref,
        },
    )
    await ProjectRepository(session).add(project)
    await session.refresh(project)  # populate server-default created_at
    return _project_response(project)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID, session: Annotated[AsyncSession, Depends(get_session)]
) -> ProjectResponse:
    project = await ProjectRepository(session).get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return _project_response(project)


@router.post(
    "/projects/{project_id}/ingest", status_code=202, response_model=IngestResponse
)
async def ingest(
    project_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_session)],
    jobs: Annotated[JobRegistry, Depends(get_jobs)],
    ingestor: Annotated[Ingestor, Depends(get_ingestor)],
) -> IngestResponse:
    if await ProjectRepository(session).get(project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    job = jobs.create(kind=JobKind.INGEST, project_id=project_id)
    background_tasks.add_task(
        run_ingest_job,
        sessionmaker=request.app.state.sessionmaker,
        jobs=jobs,
        job_id=job.id,
        project_id=project_id,
        ingestor=ingestor,
    )
    return IngestResponse(job_id=job.id, status=job.status.value)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(
    job_id: uuid.UUID, jobs: Annotated[JobRegistry, Depends(get_jobs)]
) -> JobStatusResponse:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatusResponse(
        job_id=job.id,
        kind=job.kind.value,
        status=job.status.value,
        run_id=job.run_id,
        detail=job.detail,
    )
