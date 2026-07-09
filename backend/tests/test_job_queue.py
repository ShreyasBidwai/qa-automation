"""The durable job queue + worker (B4, ADR-0034).

The reliability core, tested directly: lifecycle, restart-survival, concurrency
(FOR UPDATE SKIP LOCKED), cooperative cancellation, and retry-with-backoff. Pure
queue transitions run on the rolled-back ``db_session`` and key off a specific job
id (the table is shared); the worker/restart/concurrency tests need committed rows
across sessions, so they use their own committing sessionmaker and clean up.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models.enums import JobKind, JobStatus
from app.models.job import Job
from app.services.job_queue import ClaimedJob, JobQueue
from app.services.job_worker import JobHandler, JobWorker
from tests.factories import make_project


async def _project_id(session: AsyncSession) -> uuid.UUID:
    project = make_project()  # the conftest listener gives it a throwaway org
    session.add(project)
    await session.flush()
    return project.id


# --- pure lifecycle (rolled-back session, keyed on a specific job id) --------


async def test_enqueue_is_queued_and_readable(db_session: AsyncSession) -> None:
    queue = JobQueue(db_session)
    job = await queue.enqueue(
        kind=JobKind.RUN, project_id=await _project_id(db_session), mode="mode_b"
    )
    assert job.status == JobStatus.QUEUED and job.attempts == 0
    got = await queue.get(job.id)
    assert got is not None and got.id == job.id


async def test_claim_marks_running_and_blocks_double_claim(
    db_session: AsyncSession,
) -> None:
    queue = JobQueue(db_session)
    job = await queue.enqueue(
        kind=JobKind.INGEST, project_id=await _project_id(db_session)
    )
    claimed = await queue.claim(job.id, worker_id="w1")
    assert claimed is not None and claimed.attempts == 1
    # Already running → not claimable again.
    assert await queue.claim(job.id, worker_id="w2") is None

    assert await queue.mark_succeeded(job.id, summary={"ok": 1}) is True
    done = await queue.get(job.id)
    assert done is not None
    assert done.status == JobStatus.SUCCEEDED and done.summary == {"ok": 1}
    assert done.locked_at is None  # lease released


async def test_reclaim_stale_running_fails_only_stale_leased_jobs(
    db_session: AsyncSession,
) -> None:
    # A job whose worker died leaks its lease and lingers 'running' forever (the
    # perpetual "ongoing run" bug, ADR-0067). The reaper fails only those whose lease is
    # older than the threshold; a freshly-leased (genuinely running) job is untouched.
    queue = JobQueue(db_session)
    pid = await _project_id(db_session)
    fresh = await queue.enqueue(kind=JobKind.RUN, project_id=pid)
    stale = await queue.enqueue(kind=JobKind.INGEST, project_id=pid)
    await queue.claim(fresh.id, worker_id="w")
    await queue.claim(stale.id, worker_id="w")

    stale_job = await queue.get(stale.id)
    assert stale_job is not None
    stale_job.locked_at = datetime.now(UTC) - timedelta(hours=2)  # a dead lease
    await db_session.flush()

    reclaimed = await queue.reclaim_stale_running(older_than_seconds=3600)  # 1h
    assert reclaimed == [(stale.id, JobKind.INGEST)]

    dead = await queue.get(stale.id)
    assert dead is not None
    assert dead.status == JobStatus.FAILED and dead.locked_at is None  # lease released
    alive = await queue.get(fresh.id)
    assert alive is not None and alive.status == JobStatus.RUNNING  # fresh untouched


async def test_reclaim_stale_running_zero_threshold_reclaims_all_running(
    db_session: AsyncSession,
) -> None:
    # The startup sweep (older_than_seconds=0): with no worker alive, EVERY running job
    # is orphaned and reclaimed; queued jobs are left alone to run.
    queue = JobQueue(db_session)
    pid = await _project_id(db_session)
    running = await queue.enqueue(kind=JobKind.RUN, project_id=pid)
    queued = await queue.enqueue(kind=JobKind.RUN, project_id=pid)
    await queue.claim(running.id, worker_id="w")

    reclaimed = await queue.reclaim_stale_running(older_than_seconds=0)
    assert reclaimed == [(running.id, JobKind.RUN)]
    assert (await queue.get(queued.id)).status == JobStatus.QUEUED  # type: ignore[union-attr]


async def test_cancel_queued_job_is_never_claimed(db_session: AsyncSession) -> None:
    queue = JobQueue(db_session)
    pid = await _project_id(db_session)
    job = await queue.enqueue(kind=JobKind.RUN, project_id=pid)
    assert await queue.cancel(job.id) is True
    assert await queue.claim(job.id, worker_id="w") is None
    cancelled = await queue.get(job.id)
    assert cancelled is not None and cancelled.status == JobStatus.CANCELLED


async def test_cancel_running_job_is_not_clobbered_by_completion(
    db_session: AsyncSession,
) -> None:
    queue = JobQueue(db_session)
    pid = await _project_id(db_session)
    job = await queue.enqueue(kind=JobKind.RUN, project_id=pid)
    await queue.claim(job.id, worker_id="w")  # running
    assert await queue.cancel(job.id) is True  # cancel mid-run
    # The worker's terminal write refuses to overwrite a cancelled job.
    assert await queue.mark_succeeded(job.id, summary={"x": 1}) is False
    final = await queue.get(job.id)
    assert final is not None and final.status == JobStatus.CANCELLED


async def test_failure_retries_with_backoff_then_fails_at_cap(
    db_session: AsyncSession,
) -> None:
    queue = JobQueue(db_session)
    job = await queue.enqueue(
        kind=JobKind.RUN, project_id=await _project_id(db_session), max_attempts=2
    )

    # Attempt 1 fails → re-queued with a future available_at (backoff), detail kept.
    await queue.claim(job.id, worker_id="w")
    status = await queue.mark_failed_or_retry(
        job.id, detail="boom", backoff_base_seconds=30
    )
    assert status == JobStatus.QUEUED
    requeued = await queue.get(job.id)
    assert requeued is not None
    assert requeued.attempts == 1 and requeued.detail == "boom"
    assert requeued.available_at > datetime.now(UTC)  # backed off
    # Not yet claimable while backing off.
    assert await queue.claim(job.id, worker_id="w") is None

    # Make it due, attempt 2 (the cap) fails → terminal failed.
    requeued.available_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()
    claimed = await queue.claim(job.id, worker_id="w")
    assert claimed is not None and claimed.attempts == 2
    final_status = await queue.mark_failed_or_retry(job.id, detail="boom2")
    assert final_status == JobStatus.FAILED
    failed = await queue.get(job.id)
    assert failed is not None and failed.status == JobStatus.FAILED


# --- worker + concurrency + restart (committing sessionmaker) ----------------


@pytest_asyncio.fixture
async def sessionmaker_(
    test_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(test_database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


class _RecordingHandlers:
    """Worker handlers that record which job ids ran (and optionally raise)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.seen: list[uuid.UUID] = []
        self._fail = fail

    def as_dict(self) -> dict[JobKind, JobHandler]:
        async def handle(
            session: AsyncSession, claimed: ClaimedJob
        ) -> tuple[uuid.UUID | None, dict[str, object]]:
            self.seen.append(claimed.id)
            if self._fail:
                raise RuntimeError("boom")
            return None, {"ran": str(claimed.id)}

        return {JobKind.RUN: handle, JobKind.INGEST: handle}


async def _commit_job(
    maker: async_sessionmaker[AsyncSession], pid: uuid.UUID, **kw: object
) -> uuid.UUID:
    async with maker() as session:
        job = await JobQueue(session).enqueue(
            kind=JobKind.RUN, project_id=pid, **kw  # type: ignore[arg-type]
        )
        job_id = job.id
        await session.commit()
    return job_id


async def _cleanup(maker: async_sessionmaker[AsyncSession], pid: uuid.UUID) -> None:
    async with maker() as session:
        await session.execute(delete(Job).where(Job.project_id == pid))
        await session.commit()


async def _committed_project(maker: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with maker() as session:
        pid = await _project_id(session)
        await session.commit()
        return pid


async def test_worker_processes_a_persisted_job_after_restart(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    """Durability: a job enqueued (and never dispatched) is run by a FRESH worker
    that never saw the enqueue — i.e. it survived a restart."""
    pid = await _committed_project(sessionmaker_)
    try:
        job_id = await _commit_job(sessionmaker_, pid, mode="mode_b")
        # A brand-new worker instance (simulating a restarted process) picks it up.
        handlers = _RecordingHandlers()
        worker = JobWorker(sessionmaker_, handlers.as_dict(), worker_id="restarted")
        assert await worker.process_job(job_id) is True
        assert handlers.seen == [job_id]
        async with sessionmaker_() as session:
            done = await JobQueue(session).get(job_id)
        assert done is not None and done.status == JobStatus.SUCCEEDED
    finally:
        await _cleanup(sessionmaker_, pid)


async def test_worker_startup_reaps_orphaned_running_job(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    """A job left 'running' by a dead worker is reclaimed to 'failed' on startup — so it
    can no longer linger forever as a phantom 'ongoing run' (ADR-0067)."""
    pid = await _committed_project(sessionmaker_)
    try:
        job_id = await _commit_job(sessionmaker_, pid, mode="mode_b")
        # Claim it (→ running) then orphan it: backdate the lease as if the worker died.
        async with sessionmaker_() as session:
            queue = JobQueue(session)
            await queue.claim(job_id, worker_id="dead")
            job = await queue.get(job_id)
            assert job is not None
            job.locked_at = datetime.now(UTC) - timedelta(hours=2)
            await session.commit()

        # A fresh worker runs its startup recovery, then exits (stop already set).
        stop = asyncio.Event()
        stop.set()
        worker = JobWorker(
            sessionmaker_, _RecordingHandlers().as_dict(), worker_id="new"
        )
        await worker.run_forever(stop_event=stop)

        async with sessionmaker_() as session:
            reaped = await JobQueue(session).get(job_id)
        assert reaped is not None
        assert reaped.status == JobStatus.FAILED and reaped.locked_at is None
    finally:
        await _cleanup(sessionmaker_, pid)


async def test_concurrent_workers_never_double_claim(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    """SKIP LOCKED: N workers draining concurrently each take distinct rows."""
    pid = await _committed_project(sessionmaker_)
    try:
        job_ids = [await _commit_job(sessionmaker_, pid) for _ in range(5)]
        handlers = _RecordingHandlers()
        worker = JobWorker(sessionmaker_, handlers.as_dict(), worker_id="pool")

        # Drain concurrently; loop until all five are terminal.
        for _ in range(20):
            await asyncio.gather(*(worker.process_next() for _ in range(5)))
            async with sessionmaker_() as session:
                remaining = (
                    await session.execute(
                        select(func.count())
                        .select_from(Job)
                        .where(Job.project_id == pid, Job.status == JobStatus.QUEUED)
                    )
                ).scalar_one()
            if remaining == 0:
                break

        # Every one of MY jobs ran exactly once (no double-claim) and succeeded.
        assert sorted(i for i in handlers.seen if i in set(job_ids)) == sorted(job_ids)
        async with sessionmaker_() as session:
            queue = JobQueue(session)
            for job_id in job_ids:
                job = await queue.get(job_id)
                assert job is not None
                assert job.status == JobStatus.SUCCEEDED and job.attempts == 1
    finally:
        await _cleanup(sessionmaker_, pid)


async def test_worker_marks_failure_when_handler_raises(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    pid = await _committed_project(sessionmaker_)
    try:
        job_id = await _commit_job(sessionmaker_, pid, max_attempts=1)
        worker = JobWorker(
            sessionmaker_, _RecordingHandlers(fail=True).as_dict(), worker_id="w"
        )
        assert await worker.process_job(job_id) is True
        async with sessionmaker_() as session:
            job = await JobQueue(session).get(job_id)
        assert job is not None
        assert job.status == JobStatus.FAILED and job.detail == "RuntimeError"
    finally:
        await _cleanup(sessionmaker_, pid)


async def test_worker_requeues_on_failure_when_attempts_remain(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    pid = await _committed_project(sessionmaker_)
    try:
        job_id = await _commit_job(sessionmaker_, pid, max_attempts=3)
        worker = JobWorker(
            sessionmaker_,
            _RecordingHandlers(fail=True).as_dict(),
            worker_id="w",
            backoff_base_seconds=30,
        )
        assert await worker.process_job(job_id) is True
        async with sessionmaker_() as session:
            job = await JobQueue(session).get(job_id)
        assert job is not None
        # Re-queued for a later retry, not failed yet.
        assert job.status == JobStatus.QUEUED and job.attempts == 1
        assert job.available_at > datetime.now(UTC)
    finally:
        await _cleanup(sessionmaker_, pid)


async def test_dispatch_no_ops_on_an_already_terminal_job(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    """A cancelled job is not run by a later dispatch/claim."""
    pid = await _committed_project(sessionmaker_)
    try:
        job_id = await _commit_job(sessionmaker_, pid)
        async with sessionmaker_() as session:
            await JobQueue(session).cancel(job_id)
            await session.commit()
        handlers = _RecordingHandlers()
        worker = JobWorker(sessionmaker_, handlers.as_dict(), worker_id="w")
        assert await worker.process_job(job_id) is False
        assert handlers.seen == []
    finally:
        await _cleanup(sessionmaker_, pid)


async def test_job_with_no_handler_is_marked_failed(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    pid = await _committed_project(sessionmaker_)
    try:
        job_id = await _commit_job(sessionmaker_, pid, max_attempts=1)
        worker = JobWorker(sessionmaker_, {}, worker_id="w")  # no handlers
        assert await worker.process_job(job_id) is True
        async with sessionmaker_() as session:
            job = await JobQueue(session).get(job_id)
        assert job is not None
        assert job.status == JobStatus.FAILED and job.detail == "no_handler"
    finally:
        await _cleanup(sessionmaker_, pid)


async def test_run_forever_polls_until_stopped(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    """The poller (the restart/recovery loop) drains queued work and stops cleanly."""
    pid = await _committed_project(sessionmaker_)
    try:
        job_id = await _commit_job(sessionmaker_, pid)
        worker = JobWorker(
            sessionmaker_, _RecordingHandlers().as_dict(), worker_id="poller"
        )
        stop = asyncio.Event()
        task = asyncio.create_task(
            worker.run_forever(poll_interval_seconds=0.01, stop_event=stop)
        )
        status = None
        for _ in range(200):
            async with sessionmaker_() as session:
                job = await JobQueue(session).get(job_id)
            status = job.status if job else None
            if status == JobStatus.SUCCEEDED:
                break
            await asyncio.sleep(0.01)
        stop.set()
        await asyncio.wait_for(task, timeout=2.0)
        assert status == JobStatus.SUCCEEDED
    finally:
        await _cleanup(sessionmaker_, pid)
