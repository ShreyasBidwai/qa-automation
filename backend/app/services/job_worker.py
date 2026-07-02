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
from app.progress import (
    PHASE_RUN,
    STATUS_FAILED,
    RunProgressEmitter,
    install_emitter,
    reset_emitter,
)
from app.repositories.run_repository import RunRepository
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
        max_duration_seconds: float = 1800.0,
        incident_recorder: IncidentRecorder | None = None,
    ) -> None:
        self._sm = sessionmaker
        self._handlers = handlers
        self._worker_id = worker_id
        self._backoff = backoff_base_seconds
        # Watchdog budget: a run exceeding this is force-failed (see _run).
        self._max_duration = max_duration_seconds
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
        # Run-durability: on (re)start, reconcile runs orphaned by a crashed process
        # (left in 'running') to 'interrupted' — there is no live run in flight at
        # startup, so any 'running' row is stale.
        await self._reconcile_orphan_runs()
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
        # Run-progress (ADR-0050): install a best-effort emitter for RUN jobs so the
        # run path can emit lifecycle/step events; a non-run kind installs none, so
        # its emit() seams (if any) are silent no-ops.
        emitter = (
            RunProgressEmitter(
                self._sm, run_id=claimed.id, project_id=claimed.project_id
            )
            if claimed.kind is JobKind.RUN
            else None
        )
        token = install_emitter(emitter) if emitter is not None else None
        try:
            try:
                async with self._sm() as session:
                    # Watchdog: bound the whole run — a wedged run can never hold the
                    # queue forever (architecture-review DO-FIRST #2). A timeout is
                    # terminal (retrying a hung run just wedges again).
                    run_id, summary = await asyncio.wait_for(
                        handler(session, claimed), timeout=self._max_duration
                    )
                    await session.commit()
            except TimeoutError as exc:
                await self._on_job_failure(
                    claimed, emitter, exc, detail="watchdog_timeout", terminal=True
                )
                return
            except Exception as exc:  # task boundary: record + retry, never die
                await self._on_job_failure(
                    claimed, emitter, exc, detail=type(exc).__name__, terminal=False
                )
                return
            async with self._sm() as session:
                await JobQueue(session).mark_succeeded(
                    claimed.id, run_id=run_id, summary=summary
                )
                await session.commit()
        finally:
            if token is not None:
                reset_emitter(token)

    async def _on_job_failure(
        self,
        claimed: ClaimedJob,
        emitter: RunProgressEmitter | None,
        exc: BaseException,
        *,
        detail: str,
        terminal: bool,
    ) -> None:
        """Fail a job honestly: terminal run event + incident + run reconcile +
        queue finalize (retry unless ``terminal``). All best-effort; never raises."""
        # Terminal run-failed so a live stream closes (best-effort).
        if emitter is not None:
            await emitter.emit(
                phase=PHASE_RUN,
                step="run",
                status=STATUS_FAILED,
                detail={"error": type(exc).__name__},
            )
        # Capture a structured incident BEFORE finalizing — best-effort, so a
        # recording failure can't change the fail/retry behaviour. The phase is the
        # one tagged inward (e.g. provider) or the job kind's.
        await self._recorder.record(
            exc,
            phase=phase_of(exc, default=phase_for_job_kind(claimed.kind)),
            project_id=claimed.project_id,
            component=f"job:{claimed.kind.value}",
        )
        # Run-durability: immediately reconcile this crashed run's row (its id is the
        # job id) to 'interrupted' in a FRESH session, so the partial run + its
        # committed cases are honestly terminal without waiting for the next startup
        # sweep. Best-effort; a total DB outage defers it to that sweep.
        if claimed.kind is JobKind.RUN:
            await self._reconcile_run(claimed.id)
        await self._finalize_failure(claimed, detail, terminal=terminal)
        logger.error(
            "jobs.failed",
            extra={
                "job_id": str(claimed.id),
                "error_type": type(exc).__name__,
                "terminal": terminal,
            },
        )

    async def _finalize_failure(
        self, claimed: ClaimedJob, detail: str, *, terminal: bool = False
    ) -> None:
        async with self._sm() as session:
            await JobQueue(session).mark_failed_or_retry(
                claimed.id,
                detail=detail,
                backoff_base_seconds=self._backoff,
                terminal=terminal,
            )
            await session.commit()

    async def _reconcile_orphan_runs(self) -> None:
        """Startup sweep: mark every run still ``running`` as ``interrupted`` — they
        were orphaned by a crashed process. Best-effort: a sweep failure must never
        stop the worker from starting."""
        try:
            async with self._sm() as session:
                ids = await RunRepository(session).interrupt_stale_running()
                await session.commit()
            if ids:
                logger.info("jobs.reconciled_orphan_runs", extra={"count": len(ids)})
        except Exception:  # noqa: BLE001 — never block worker startup
            logger.exception("jobs.reconcile_orphan_runs_failed")

    async def _reconcile_run(self, run_id: uuid.UUID) -> None:
        """Best-effort: compare-and-set this crashed run's row (id == job id) to
        ``interrupted`` in a fresh session — survives the job's own rollback. A
        legitimately-finished run is untouched (CAS on ``running``)."""
        try:
            async with self._sm() as session:
                await RunRepository(session).mark_interrupted(run_id)
                await session.commit()
        except Exception:  # noqa: BLE001 — best-effort; the startup sweep is the net
            logger.warning("jobs.run_reconcile_failed", extra={"job_id": str(run_id)})
