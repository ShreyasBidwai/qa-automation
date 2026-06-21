"""Operator status view (B4, ADR-0034/0035).

A minimal, read-only, CROSS-TENANT surface for whoever runs the instance: queue
depth, running/stuck/failed jobs, runner health. Gated by the instance-level
operator flag (``OperatorUser`` → 403 for a non-operator), NOT org RBAC — this
reports across all tenants by design. It's the seed of ops visibility, not an
admin panel: no mutation endpoints.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.enums import JobStatus
from app.models.job import Job
from app.services.job_queue import JobQueue

from .deps import OperatorUser, get_session
from .schemas import JobListResponse, JobSummary, QueueStatsResponse

router = APIRouter(prefix="/api/v1/ops", tags=["operator"])


def _settings() -> Settings:
    return get_settings()


def _job_summary(job: Job) -> JobSummary:
    return JobSummary(
        id=job.id,
        kind=job.kind.value,
        status=job.status.value,
        project_id=job.project_id,
        mode=job.mode,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        detail=job.detail,
        created_at=job.created_at,
        locked_at=job.locked_at,
        finished_at=job.finished_at,
    )


@router.get("/queue", response_model=QueueStatsResponse)
async def queue_stats(
    operator: OperatorUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(_settings)],
) -> QueueStatsResponse:
    """Queue depth + lifecycle counts + stuck count + runner health (cross-tenant)."""
    queue = JobQueue(session)
    counts = await queue.counts_by_status()
    stuck = await queue.stuck_jobs(
        older_than_seconds=settings.job_stuck_after_seconds, limit=1000
    )
    return QueueStatsResponse(
        queued=counts.get(JobStatus.QUEUED, 0),
        running=counts.get(JobStatus.RUNNING, 0),
        succeeded=counts.get(JobStatus.SUCCEEDED, 0),
        failed=counts.get(JobStatus.FAILED, 0),
        cancelled=counts.get(JobStatus.CANCELLED, 0),
        stuck=len(stuck),
        total=sum(counts.values()),
        runner_healthy=len(stuck) == 0,
    )


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    operator: OperatorUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    status: Annotated[JobStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> JobListResponse:
    """Recent jobs across all tenants, optionally filtered by status (e.g. failed)."""
    queue = JobQueue(session)
    jobs = (
        await queue.list_by_status(status, limit=limit)
        if status is not None
        else await queue.list_recent(limit=limit)
    )
    return JobListResponse(items=[_job_summary(job) for job in jobs], total=len(jobs))
