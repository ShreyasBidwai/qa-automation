"""Decoupled execution topology (B5, ADR-0036).

Proves the control/execution split end-to-end in the fast lane: a toolchain-FREE
backend (no executor on app.state) enqueues a run; a separate runner worker — the
thing that carries an executor — claims it from the durable queue, executes, and
the results/findings flow back through the DB. Plus: a cancelled run is respected
by a worker (B4 semantics preserved). The worker here runs the round-trip stub
executor (no toolchains needed to prove the topology); the real toolchain worker
image is exercised by the heavy lanes (test_runner_worker_image.py).
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text

from app.api.composition import StubIngestor, StubRunExecutor
from app.api.jobs import make_handlers
from app.services.job_queue import JobQueue
from app.services.job_worker import JobWorker

_RUN_BODY = {"mode": "mode_b", "strategy": "full_sweep"}


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _signup(client: AsyncClient) -> str:
    email = f"topo-{uuid.uuid4().hex[:12]}@example.test"
    resp = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": "passw0rd1"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def _create_project(client: AsyncClient, token: str) -> str:
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Topo", "repo_url": "https://git/topo.git"},
        headers=_h(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _runner_worker(app: FastAPI) -> JobWorker:
    """A runner worker like `python -m app.worker` builds — it carries the
    executors; the backend does not."""
    return JobWorker(
        app.state.sessionmaker,
        make_handlers(ingestor=StubIngestor(), executor=StubRunExecutor()),
        worker_id="test-runner",
    )


async def _delete_project(app: FastAPI, project_id: str) -> None:
    """Remove the committed project (cascades to its runs/findings/jobs) so this
    test's findings don't pollute the shared DB's global queries."""
    async with app.state.sessionmaker() as session:
        await session.execute(
            text("DELETE FROM projects WHERE id = :pid"), {"pid": project_id}
        )
        await session.commit()


async def test_run_dispatched_by_slim_backend_executes_on_a_worker(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = app_client
    # The backend is the toolchain-free control plane: no executor on app.state.
    assert getattr(app.state, "run_executor", None) is None

    token = await _signup(client)
    project_id = await _create_project(client, token)
    try:
        # Backend enqueues — it does NOT execute in-process (no executor).
        enqueue = await client.post(
            f"/api/v1/projects/{project_id}/runs", json=_RUN_BODY, headers=_h(token)
        )
        assert enqueue.status_code == 202
        job_id = enqueue.json()["run_id"]
        assert (await client.get(f"/api/v1/runs/{job_id}", headers=_h(token))).json()[
            "status"
        ] == "queued"

        # A separate runner worker claims it from the queue and executes it.
        worker = _runner_worker(app)
        status = "queued"
        for _ in range(10):
            await worker.process_next()
            status = (
                await client.get(f"/api/v1/runs/{job_id}", headers=_h(token))
            ).json()["status"]
            if status in ("succeeded", "failed"):
                break
        assert status == "succeeded"

        # Results/findings produced by the worker flowed back through the DB.
        findings = await client.get(
            f"/api/v1/runs/{job_id}/findings", headers=_h(token)
        )
        assert findings.json()["count"] >= 1
    finally:
        await _delete_project(app, project_id)


async def test_cancelled_dispatched_run_is_not_executed(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = app_client
    token = await _signup(client)
    project_id = await _create_project(client, token)
    try:
        job_id = (
            await client.post(
                f"/api/v1/projects/{project_id}/runs", json=_RUN_BODY, headers=_h(token)
            )
        ).json()["run_id"]

        # Cancel the queued run (B4 cancel semantics, preserved).
        async with app.state.sessionmaker() as session:
            assert await JobQueue(session).cancel(uuid.UUID(job_id)) is True
            await session.commit()

        # A worker attempting to claim it respects the cancellation — no execution.
        worker = _runner_worker(app)
        assert await worker.process_job(uuid.UUID(job_id)) is False

        status = await client.get(f"/api/v1/runs/{job_id}", headers=_h(token))
        assert status.json()["status"] == "cancelled"
        findings = await client.get(
            f"/api/v1/runs/{job_id}/findings", headers=_h(token)
        )
        assert findings.json()["count"] == 0
    finally:
        await _delete_project(app, project_id)
