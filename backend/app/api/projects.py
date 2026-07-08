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

from app.brain.modules import aggregate_modules
from app.core.permissions import Permission
from app.models.enums import JobKind, NodeKind
from app.models.project import Project
from app.reporting.project_summary import (
    STATUS_NEVER_RUN,
    ProjectSummary,
    ProjectSummaryReader,
)
from app.repositories.edge_repository import EdgeRepository
from app.repositories.node_repository import NodeRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository
from app.services.job_queue import JobQueue

from .authz import authorize_org, authorize_project
from .deps import CurrentUser, get_session
from .jobs import dispatch_job
from .quota import enforce_org_not_suspended
from .schemas import (
    DbStateTierResponse,
    DbStateTierUpdate,
    IngestResponse,
    JobStatusResponse,
    LastRunSummary,
    ModelKindCount,
    ModelStatsResponse,
    ModuleListResponse,
    ModuleSummaryResponse,
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
        ai_provider=settings.get("ai_provider"),
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
            "ai_provider": body.ai_provider,  # null ⇒ instance default at run time
        },
    )
    await ProjectRepository(session).add(project)
    await session.refresh(project)  # populate server-default created_at
    return _project_response(project)


def _project_list_item(
    project: Project, summary: ProjectSummary | None
) -> ProjectListItem:
    settings = project.settings
    last_run: LastRunSummary | None = None
    if summary is not None and summary.last_run is not None:
        run = summary.last_run
        last_run = LastRunSummary(
            run_id=run.id,
            mode=run.mode.value,
            status=run.status,
            pass_rate=summary.pass_rate,
            finished_at=run.finished_at,
            created_at=run.created_at,
        )
    return ProjectListItem(
        id=project.id,
        name=project.name,
        slug=project.slug,
        repo_url=str(settings.get("repo_url", "")),
        app_url=project.app_url,
        created_at=project.created_at,
        stack=settings.get("stack"),
        status=summary.status if summary is not None else STATUS_NEVER_RUN,
        open_findings_count=(summary.open_findings_count if summary is not None else 0),
        last_run=last_run,
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
    # Batched per-project summary (last-run + pass-rate + open-findings + status) —
    # a fixed number of grouped queries for the whole page, no N+1 (ADR-0045).
    summaries = await ProjectSummaryReader(session).summaries_for(
        [project.id for project in projects]
    )
    return ProjectListResponse(
        items=[
            _project_list_item(project, summaries.get(project.id))
            for project in projects
        ],
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


@router.get("/projects/{project_id}/model", response_model=ModelStatsResponse)
async def get_project_model(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ModelStatsResponse:
    """The built-model (Brain) summary: is it built, how many nodes/edges, of what
    kinds, and when it was last built (VIEW). Drives the Project view's Model card."""
    await authorize_project(session, project_id, current_user, Permission.VIEW)
    nodes = NodeRepository(session)
    counts = await nodes.counts_by_kind(project_id)
    node_count = sum(counts.values())
    edge_count = await EdgeRepository(session).count_for_project(project_id)
    return ModelStatsResponse(
        built=node_count > 0,
        node_count=node_count,
        edge_count=edge_count,
        # Most-numerous kind first, so "42 endpoints" leads the breakdown.
        nodes_by_kind=[
            ModelKindCount(kind=kind.value, count=count)
            for kind, count in sorted(
                counts.items(), key=lambda kv: (-kv[1], kv[0].value)
            )
        ],
        last_built_at=await nodes.last_built_at(project_id) if node_count else None,
    )


@router.get("/projects/{project_id}/modules", response_model=ModuleListResponse)
async def list_project_modules(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ModuleListResponse:
    """The project's feature areas ("modules"), derived from the Brain's testable
    targets (ADR-0061), each with its endpoint/page counts — so a run can be scoped to
    just the modules a QA cares about (VIEW). Empty until the model is built."""
    await authorize_project(session, project_id, current_user, Permission.VIEW)
    repo = NodeRepository(session)
    nodes = []
    for kind in (NodeKind.ENDPOINT, NodeKind.PAGE):
        nodes.extend(await repo.list_by_kind(project_id, kind))
    return ModuleListResponse(
        modules=[
            ModuleSummaryResponse(
                key=module.key,
                label=module.label,
                endpoint_count=module.endpoint_count,
                page_count=module.page_count,
                total=module.total,
            )
            for module in aggregate_modules(nodes)
        ]
    )


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
    if (
        changes.get("repo_url") is not None
        or "stack" in changes
        or "ai_provider" in changes
    ):
        settings = dict(project.settings)
        if changes.get("repo_url") is not None:
            settings["repo_url"] = changes["repo_url"]
        if "stack" in changes:
            settings["stack"] = changes["stack"]
        if "ai_provider" in changes:  # null clears it → instance default at run time
            settings["ai_provider"] = changes["ai_provider"]
        project.settings = settings  # reassign so JSONB change is tracked

    await session.flush()
    await session.refresh(project)
    return _project_response(project)


@router.get("/projects/{project_id}/db-state-tier", response_model=DbStateTierResponse)
async def get_db_state_tier(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DbStateTierResponse:
    """The project's DB-state-testing tier (B10, ADR-0043). VIEW; 404 if hidden."""
    project = await authorize_project(
        session, project_id, current_user, Permission.VIEW
    )
    return DbStateTierResponse(project_id=project.id, tier=project.db_state_tier)


@router.put("/projects/{project_id}/db-state-tier", response_model=DbStateTierResponse)
async def set_db_state_tier(
    project_id: uuid.UUID,
    body: DbStateTierUpdate,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DbStateTierResponse:
    """Set the DB-state-testing tier (B10, ADR-0043). MANAGE_PROJECT; bad value → 422.

    Raising to ``full`` records intent only; the non-prod safety gate is enforced at
    execution time, when a disposable target is actually written to — so flipping the
    tier can never, by itself, cause a write to a real database.
    """
    project = await authorize_project(
        session, project_id, current_user, Permission.MANAGE_PROJECT
    )
    project.db_state_tier = body.tier
    await session.flush()
    return DbStateTierResponse(project_id=project.id, tier=project.db_state_tier)


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
) -> IngestResponse:
    project = await authorize_project(session, project_id, current_user, Permission.RUN)
    # A suspended org starts no new work (ADR-0068).
    await enforce_org_not_suspended(session, project.org_id)
    # Single attempt — ingest rebuilds the Brain (non-idempotent); the queue still
    # supports retry-with-backoff (ADR-0034) for jobs that opt in.
    job = await JobQueue(session).enqueue(
        kind=JobKind.INGEST, project_id=project_id, max_attempts=1
    )
    # Commit now so the durable row is visible to whoever executes it.
    await session.commit()
    # Decoupled topology (B5, ADR-0036): dispatch in-process only if this node has
    # an ingestor (single-box stub); otherwise a runner worker claims it.
    ingestor = getattr(request.app.state, "ingestor", None)
    if ingestor is not None:
        background_tasks.add_task(
            dispatch_job,
            sessionmaker=request.app.state.sessionmaker,
            job_id=job.id,
            ingestor=ingestor,
        )
    return IngestResponse(job_id=job.id, status=job.status.value)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(
    job_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JobStatusResponse:
    job = await JobQueue(session).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatusResponse(
        job_id=job.id,
        kind=job.kind.value,
        status=job.status.value,
        run_id=job.run_id,
        detail=job.detail,
    )
