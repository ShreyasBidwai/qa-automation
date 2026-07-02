"""Watchdog: a run that never finishes is force-failed TERMINALLY, so a hung run
can never hold the single-worker queue forever (architecture-review DO-FIRST #2).
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from fastapi import FastAPI

from app.models.enums import JobKind, JobStatus
from app.services.job_queue import ClaimedJob, JobQueue
from app.services.job_worker import JobWorker


async def _signup(client: httpx.AsyncClient) -> str:
    email = f"wd-{uuid.uuid4().hex[:10]}@e.test"
    resp = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": "watchdogpw1"}
    )
    return resp.json()["access_token"]


async def test_watchdog_terminally_fails_a_wedged_run(
    app_client: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, app = app_client
    token = await _signup(client)
    pid = (
        await client.post(
            "/api/v1/projects",
            json={"name": "WD", "repo_url": "/r"},
            headers={"Authorization": f"Bearer {token}"},
        )
    ).json()["id"]

    # Enqueue a RUN job whose handler will hang past the (tiny) watchdog budget.
    async with app.state.sessionmaker() as session:
        job = await JobQueue(session).enqueue(
            kind=JobKind.RUN, project_id=uuid.UUID(pid), mode="mode_b"
        )
        await session.commit()
        job_id = job.id

    async def hang(session: object, claimed: ClaimedJob) -> object:
        await asyncio.sleep(3600)  # never returns — the watchdog must cancel it
        return None, {}

    worker = JobWorker(
        app.state.sessionmaker,
        {JobKind.RUN: hang},  # type: ignore[dict-item]
        worker_id="watchdog-test",
        max_duration_seconds=0.05,  # fire almost immediately
    )
    await worker.process_next()

    async with app.state.sessionmaker() as session:
        row = await JobQueue(session).get(job_id)

    assert row is not None
    assert row.status is JobStatus.FAILED  # failed, not stuck 'running'
    assert row.detail == "watchdog_timeout"
    assert row.attempts == 1  # terminal — NOT re-queued for another wedged attempt
    assert row.finished_at is not None
