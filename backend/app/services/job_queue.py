"""The durable job queue on Postgres (B4, ADR-0034).

Pure queue operations over the ``jobs`` table — no API/port knowledge (handlers
live in the API layer). Claims use ``SELECT … FOR UPDATE SKIP LOCKED`` so N workers
never grab the same row; terminal writes are compare-and-set against ``running`` so
a cancellation can't be clobbered. Retry-with-backoff re-queues a failed job with a
future ``available_at`` until ``max_attempts``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobKind, JobStatus
from app.models.job import Job

# Statuses a job can still leave (claimable or cancellable).
_ACTIVE: tuple[JobStatus, ...] = (JobStatus.QUEUED, JobStatus.RUNNING)


@dataclass(frozen=True)
class ClaimedJob:
    """A detached snapshot of a claimed job (carried across worker sessions)."""

    id: uuid.UUID
    kind: JobKind
    project_id: uuid.UUID
    mode: str | None
    payload: dict[str, Any]
    attempts: int


class JobQueue:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- enqueue / read ------------------------------------------------------

    async def enqueue(
        self,
        *,
        kind: JobKind,
        project_id: uuid.UUID,
        mode: str | None = None,
        payload: dict[str, Any] | None = None,
        max_attempts: int = 3,
    ) -> Job:
        job = Job(
            kind=kind,
            project_id=project_id,
            mode=mode,
            payload=payload or {},
            max_attempts=max_attempts,
            status=JobStatus.QUEUED,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: uuid.UUID) -> Job | None:
        return await self.session.get(Job, job_id)

    # --- claim (FOR UPDATE SKIP LOCKED) --------------------------------------

    async def claim(self, job_id: uuid.UUID, *, worker_id: str) -> ClaimedJob | None:
        """Claim one specific job if it is queued and due (the dispatch hint)."""
        stmt = (
            select(Job)
            .where(
                Job.id == job_id,
                Job.status == JobStatus.QUEUED,
                Job.available_at <= func.now(),
            )
            .with_for_update(skip_locked=True)
        )
        return await self._take((await self.session.scalars(stmt)).first(), worker_id)

    async def claim_next(self, *, worker_id: str) -> ClaimedJob | None:
        """Claim the oldest due queued job, skipping rows other workers hold."""
        stmt = (
            select(Job)
            .where(Job.status == JobStatus.QUEUED, Job.available_at <= func.now())
            .order_by(Job.available_at, Job.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return await self._take((await self.session.scalars(stmt)).first(), worker_id)

    async def _take(self, job: Job | None, worker_id: str) -> ClaimedJob | None:
        if job is None:
            return None
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.locked_at = func.now()
        job.locked_by = worker_id
        await self.session.flush()
        return ClaimedJob(
            id=job.id,
            kind=job.kind,
            project_id=job.project_id,
            mode=job.mode,
            payload=dict(job.payload),
            attempts=job.attempts,
        )

    # --- terminal transitions (compare-and-set vs running) -------------------

    async def mark_succeeded(
        self,
        job_id: uuid.UUID,
        *,
        run_id: uuid.UUID | None = None,
        summary: dict[str, Any] | None = None,
    ) -> bool:
        job = await self._lock(job_id)
        if job is None or job.status != JobStatus.RUNNING:
            return False  # cancelled mid-run (or gone) → don't clobber
        job.status = JobStatus.SUCCEEDED
        job.run_id = run_id
        job.summary = summary
        job.finished_at = func.now()
        self._release(job)
        await self.session.flush()
        return True

    async def mark_failed_or_retry(
        self,
        job_id: uuid.UUID,
        *,
        detail: str,
        backoff_base_seconds: float = 2.0,
    ) -> JobStatus | None:
        """Re-queue with exponential backoff under the cap, else mark failed."""
        job = await self._lock(job_id)
        if job is None or job.status != JobStatus.RUNNING:
            return None
        job.detail = detail
        if job.attempts < job.max_attempts:
            delay = backoff_base_seconds * (2 ** (job.attempts - 1))
            job.status = JobStatus.QUEUED
            job.available_at = datetime.now(UTC) + timedelta(seconds=delay)
        else:
            job.status = JobStatus.FAILED
            job.finished_at = func.now()
        self._release(job)
        await self.session.flush()
        return job.status

    async def cancel(self, job_id: uuid.UUID) -> bool:
        """Cancel a queued (never runs) or running (cooperative) job."""
        job = await self._lock(job_id)
        if job is None or job.status not in _ACTIVE:
            return False
        job.status = JobStatus.CANCELLED
        job.finished_at = func.now()
        self._release(job)
        await self.session.flush()
        return True

    async def _lock(self, job_id: uuid.UUID) -> Job | None:
        stmt = select(Job).where(Job.id == job_id).with_for_update()
        return (await self.session.scalars(stmt)).first()

    @staticmethod
    def _release(job: Job) -> None:
        job.locked_at = None
        job.locked_by = None

    # --- operator stats (cross-tenant; ADR-0035) -----------------------------

    async def counts_by_status(self) -> dict[JobStatus, int]:
        rows = (
            await self.session.execute(
                select(Job.status, func.count()).group_by(Job.status)
            )
        ).all()
        return {status: count for status, count in rows}

    async def queue_depth(self) -> int:
        return await self._count(Job.status == JobStatus.QUEUED)

    async def stuck_jobs(
        self, *, older_than_seconds: float, limit: int = 50
    ) -> list[Job]:
        """Running jobs whose lease is older than the threshold (likely wedged)."""
        cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
        stmt = (
            select(Job)
            .where(Job.status == JobStatus.RUNNING, Job.locked_at < cutoff)
            .order_by(Job.locked_at)
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def list_by_status(self, status: JobStatus, *, limit: int = 50) -> list[Job]:
        stmt = (
            select(Job)
            .where(Job.status == status)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def list_recent(self, *, limit: int = 50) -> list[Job]:
        stmt = select(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(limit)
        return list((await self.session.scalars(stmt)).all())

    async def _count(self, *where: ColumnElement[bool]) -> int:
        stmt = select(func.count()).select_from(Job).where(*where)
        return int(await self.session.scalar(stmt) or 0)
