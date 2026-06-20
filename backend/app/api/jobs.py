"""In-process background jobs — no new infra (ADR-0026).

A ``JobRegistry`` (a dict on ``app.state``) tracks long-running ingest/run work
kicked off via FastAPI ``BackgroundTasks``. Each background runner opens its OWN
session from the sessionmaker (the request session is gone by the time it runs),
drives the injected port, and records status + result on the job. The ``jobs``
table + a real broker (TRD §9) are a later upgrade behind this same poll contract.
"""

from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .ports import Ingestor, RunExecutor, RunRequest

logger = logging.getLogger("app.api.jobs")


class JobKind(str, enum.Enum):
    INGEST = "ingest"
    RUN = "run"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class Job:
    """The pollable status handle for one background operation."""

    id: uuid.UUID
    kind: JobKind
    project_id: uuid.UUID
    status: JobStatus = JobStatus.PENDING
    mode: str | None = None  # run jobs: which mode was requested
    run_id: uuid.UUID | None = None  # run jobs: the DB run the orchestrator created
    summary: dict[str, Any] | None = None
    detail: str | None = None  # failure: the error type (no secrets)


class JobRegistry:
    """An in-memory registry of jobs (per-process, per-app)."""

    def __init__(self) -> None:
        self._jobs: dict[uuid.UUID, Job] = {}

    def create(
        self,
        *,
        kind: JobKind,
        project_id: uuid.UUID,
        mode: str | None = None,
    ) -> Job:
        job = Job(id=uuid.uuid4(), kind=kind, project_id=project_id, mode=mode)
        self._jobs[job.id] = job
        return job

    def get(self, job_id: uuid.UUID) -> Job | None:
        return self._jobs.get(job_id)


async def run_ingest_job(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    jobs: JobRegistry,
    job_id: uuid.UUID,
    project_id: uuid.UUID,
    ingestor: Ingestor,
) -> None:
    """Background: build the Brain for a project, recording job status."""
    job = jobs.get(job_id)
    if job is None:  # registry evicted (e.g. restart) — nothing to update
        return
    job.status = JobStatus.RUNNING
    try:
        async with sessionmaker() as session:
            job.summary = await ingestor.ingest(session=session, project_id=project_id)
            await session.commit()
        job.status = JobStatus.SUCCEEDED
    except Exception as exc:  # task boundary: record + log, never die silently
        job.status = JobStatus.FAILED
        job.detail = type(exc).__name__
        logger.error(
            "api.ingest_job_failed",
            extra={"job_id": str(job_id), "error_type": type(exc).__name__},
        )


async def run_run_job(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    jobs: JobRegistry,
    job_id: uuid.UUID,
    project_id: uuid.UUID,
    executor: RunExecutor,
    request: RunRequest,
) -> None:
    """Background: execute a run via the orchestrators, recording job status."""
    job = jobs.get(job_id)
    if job is None:
        return
    job.status = JobStatus.RUNNING
    try:
        async with sessionmaker() as session:
            execution = await executor.execute(
                session=session, project_id=project_id, request=request
            )
            await session.commit()
        job.run_id = execution.run_id
        job.summary = execution.summary
        job.status = JobStatus.SUCCEEDED
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.detail = type(exc).__name__
        logger.error(
            "api.run_job_failed",
            extra={"job_id": str(job_id), "error_type": type(exc).__name__},
        )
