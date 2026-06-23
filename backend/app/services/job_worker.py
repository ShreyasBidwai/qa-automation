"""The durable-queue worker (B4, ADR-0034).

Claims jobs from ``JobQueue`` and runs them through injected handlers (the handlers
know about the run/ingest ports; the worker stays port-agnostic so it lives in the
service layer). Each phase — claim, execute, finalize — is its own short
transaction (no row lock held across the long handler), mirroring the prior
background-runner shape. ``process_job`` is the API dispatch hint; ``process_next``
+ ``run_forever`` are the poller that recovers orphans/retries after a restart.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.incidents import IncidentRecorder, phase_for_job_kind, phase_of
from app.models.enums import JobKind
from app.services.job_queue import ClaimedJob, JobQueue

logger = logging.getLogger("app.jobs.worker")

# A handler runs the job's work against a session and returns (run_id, summary).
JobHandler = Callable[
    [AsyncSession, ClaimedJob], Awaitable[tuple[uuid.UUID | None, dict[str, Any]]]
]


class JobWorker:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        handlers: dict[JobKind, JobHandler],
        *,
        worker_id: str = "worker",
        backoff_base_seconds: float = 2.0,
        incident_recorder: IncidentRecorder | None = None,
    ) -> None:
        self._sm = sessionmaker
        self._handlers = handlers
        self._worker_id = worker_id
        self._backoff = backoff_base_seconds
        # The universal capture seam: every autonomous failure surfaces here. Records
        # in a fresh session (best-effort) so it survives the job's own rollback.
        self._recorder = incident_recorder or IncidentRecorder(sessionmaker)

    async def process_job(self, job_id: uuid.UUID) -> bool:
        """Process one specific job (the API dispatch hint). False if not claimable."""
        async with self._sm() as session:
            claimed = await JobQueue(session).claim(job_id, worker_id=self._worker_id)
            await session.commit()
        if claimed is None:
            return False
        await self._run(claimed)
        return True

    async def process_next(self) -> bool:
        """Claim + run the next due job. False if the queue had nothing to do."""
        async with self._sm() as session:
            claimed = await JobQueue(session).claim_next(worker_id=self._worker_id)
            await session.commit()
        if claimed is None:
            return False
        await self._run(claimed)
        return True

    async def run_forever(
        self,
        *,
        poll_interval_seconds: float = 1.0,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Poll until stopped — the durability/recovery loop (gated in lifespan)."""
        while stop_event is None or not stop_event.is_set():
            try:
                worked = await self.process_next()
            except Exception:  # never let the poller die on one bad job
                logger.exception("jobs.poll_error")
                worked = False
            if not worked:
                await asyncio.sleep(poll_interval_seconds)

    async def _run(self, claimed: ClaimedJob) -> None:
        handler = self._handlers.get(claimed.kind)
        if handler is None:
            await self._finalize_failure(claimed, "no_handler")
            return
        try:
            async with self._sm() as session:
                run_id, summary = await handler(session, claimed)
                await session.commit()
        except Exception as exc:  # task boundary: record + retry, never die silently
            # Capture a structured incident BEFORE finalizing — best-effort, so a
            # recording failure can't change the existing fail/retry behaviour. The
            # phase is the one tagged inward (e.g. provider) or the job kind's.
            await self._recorder.record(
                exc,
                phase=phase_of(exc, default=phase_for_job_kind(claimed.kind)),
                project_id=claimed.project_id,
                component=f"job:{claimed.kind.value}",
            )
            await self._finalize_failure(claimed, type(exc).__name__)
            logger.error(
                "jobs.failed",
                extra={"job_id": str(claimed.id), "error_type": type(exc).__name__},
            )
            return
        async with self._sm() as session:
            await JobQueue(session).mark_succeeded(
                claimed.id, run_id=run_id, summary=summary
            )
            await session.commit()

    async def _finalize_failure(self, claimed: ClaimedJob, detail: str) -> None:
        async with self._sm() as session:
            await JobQueue(session).mark_failed_or_retry(
                claimed.id, detail=detail, backoff_base_seconds=self._backoff
            )
            await session.commit()
