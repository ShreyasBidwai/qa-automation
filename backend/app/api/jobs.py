"""API ↔ durable-queue glue (B4, ADR-0034).

The queue itself is durable (``app.services.job_queue`` on the ``jobs`` table) and a
worker poller drains it (``app.services.job_worker``). This module builds the
job *handlers* — the closures that bridge a claimed job to the run/ingest ports —
and the ``dispatch_job`` background-task trigger the endpoints fire so a
just-enqueued job runs immediately in-process (low-latency path; the poller is the
restart/retry safety net).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.enums import JobKind
from app.services.job_queue import ClaimedJob
from app.services.job_worker import JobHandler, JobWorker

from .ports import Ingestor, RunExecutor, run_request_from_payload


def make_handlers(
    *, ingestor: Ingestor | None = None, executor: RunExecutor | None = None
) -> dict[JobKind, JobHandler]:
    """Handlers for the kinds whose port is available (others stay unhandled)."""
    handlers: dict[JobKind, JobHandler] = {}
    if ingestor is not None:
        handlers[JobKind.INGEST] = _ingest_handler(ingestor)
    if executor is not None:
        handlers[JobKind.RUN] = _run_handler(executor)
    return handlers


def _ingest_handler(ingestor: Ingestor) -> JobHandler:
    async def handle(session: AsyncSession, claimed: ClaimedJob):  # type: ignore[no-untyped-def]
        summary = await ingestor.ingest(session=session, project_id=claimed.project_id)
        return None, summary

    return handle


def _run_handler(executor: RunExecutor) -> JobHandler:
    async def handle(session: AsyncSession, claimed: ClaimedJob):  # type: ignore[no-untyped-def]
        execution = await executor.execute(
            session=session,
            project_id=claimed.project_id,
            request=run_request_from_payload(claimed.payload),
        )
        return execution.run_id, execution.summary

    return handle


async def dispatch_job(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    ingestor: Ingestor | None = None,
    executor: RunExecutor | None = None,
) -> None:
    """Background-task trigger: process one just-enqueued job in-process (ADR-0034).

    The job is already a durable row; this just runs it now instead of waiting for
    the poller. If the row was claimed/cancelled meanwhile, ``process_job`` no-ops.
    """
    worker = JobWorker(
        sessionmaker,
        make_handlers(ingestor=ingestor, executor=executor),
        worker_id="api-dispatch",
    )
    await worker.process_job(job_id)
