"""Project + ingest + job-status routes (TRD §4, ADR-0026).

Thin: validate, enforce tenancy, persist the project / enqueue background work.
The Brain build runs as an in-process background job; the client polls
``GET /jobs/{job_id}``.
"""

from __future__ import annotations

import re
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.models.project import Project
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository

from .authz import authorize_org, authorize_project
from .deps import CurrentUser, get_ingestor, get_jobs, get_session
from .jobs import JobKind, JobRegistry, run_ingest_job
from .ports import Ingestor
from .schemas import (
    IngestResponse,
    JobStatusResponse,
    ProjectCreate,
    ProjectListItem,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
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
        app_url=project.app_url,  # promoted to a column (Sprint B1)
        auth_config_ref=settings.get("auth_config_ref"),
        stack=settings.get("stack"),
        created_at=project.created_at,
    )


@router.post("/projects", status_code=201, response_model=ProjectResponse)
async def create_project(
    body: ProjectCreate,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectResponse:
    # Target org: the named one, else the caller's personal org (ADR-0032). The
    # caller must have MANAGE_PROJECT there (404 if not a member, 403 if viewer).
    if body.org_id is not None:
        org_id = body.org_id
    else:
        personal = await OrganizationRepository(session).get_personal_org(
            current_user.id
        )
        if personal is None:  # every user gets one on signup; defensive
            raise HTTPException(status_code=409, detail="no personal organization")
        org_id = personal.id
    await authorize_org(session, org_id, current_user, Permission.MANAGE_PROJECT)

    project = Project(
        name=body.name,
        slug=_slug(body.name),
        app_url=body.app_url,  # first-class column (Sprint B1)
        org_id=org_id,  # org-scoped (ADR-0032)
        created_by=current_user.id,  # provenance only
        settings={
            "repo_url": body.repo_url,
            "auth_config_ref": body.auth_config_ref,
            "stack": body.stack,
        },
    )
    await ProjectRepository(session).add(project)
    await session.refresh(project)  # populate server-default created_at
    return _project_response(project)


def _project_list_item(project: Project) -> ProjectListItem:
    settings = project.settings
    return ProjectListItem(
        id=project.id,
        name=project.name,
        slug=project.slug,
        repo_url=str(settings.get("repo_url", "")),
        app_url=project.app_url,
        created_at=project.created_at,
    )


@router.get("/projects", response_model=ProjectListResponse)
async def list_projects(
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectListResponse:
    org_ids = await OrganizationRepository(session).member_org_ids(current_user.id)
    repo = ProjectRepository(session)
    projects = await repo.list(limit=limit, offset=offset, org_ids=org_ids)
    return ProjectListResponse(
        items=[_project_list_item(project) for project in projects],
        total=await repo.count(org_ids=org_ids),
        limit=limit,
        offset=offset,
    )


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectResponse:
    project = await authorize_project(
        session, project_id, current_user, Permission.VIEW
    )
    return _project_response(project)


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectResponse:
    """Partial-update a project (name, repo_url, app_url, stack). 404 / 422.

    Only fields present in the body change. ``app_url`` / ``stack`` may be set to
    null to clear them; ``name`` / ``repo_url`` are required-if-present (a null is
    ignored rather than nulling a needed field).
    """
    project = await authorize_project(
        session, project_id, current_user, Permission.MANAGE_PROJECT
    )

    changes = body.model_dump(exclude_unset=True)
    if changes.get("name") is not None:
        project.name = changes["name"]
    if "app_url" in changes:
        project.app_url = changes["app_url"]
    if changes.get("repo_url") is not None or "stack" in changes:
        settings = dict(project.settings)
        if changes.get("repo_url") is not None:
            settings["repo_url"] = changes["repo_url"]
        if "stack" in changes:
            settings["stack"] = changes["stack"]
        project.settings = settings  # reassign so JSONB change is tracked

    await session.flush()
    await session.refresh(project)
    return _project_response(project)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Soft-delete a project (ADR-0029): hidden from reads, history preserved."""
    await authorize_project(
        session, project_id, current_user, Permission.MANAGE_PROJECT
    )
    await ProjectRepository(session).soft_delete(project_id)
    return Response(status_code=204)


@router.post(
    "/projects/{project_id}/ingest", status_code=202, response_model=IngestResponse
)
async def ingest(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    request: Request,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_session)],
    jobs: Annotated[JobRegistry, Depends(get_jobs)],
    ingestor: Annotated[Ingestor, Depends(get_ingestor)],
) -> IngestResponse:
    await authorize_project(session, project_id, current_user, Permission.RUN)
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
    job_id: uuid.UUID,
    current_user: CurrentUser,
    jobs: Annotated[JobRegistry, Depends(get_jobs)],
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
