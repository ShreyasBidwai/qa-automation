"""Operator status view (B4, ADR-0034/0035).

The instance-level operator gate (403 for a non-operator, 401 unauthenticated) and
the cross-tenant queue snapshot: depth, stuck/failed jobs, runner health. Jobs are
seeded through the app's committing sessionmaker; the operator flag is set out of
band (there is no API for it). Counts are asserted inclusively (>=) so the shared
test DB's other rows don't make the assertions brittle.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient

from app.models.enums import JobKind, JobStatus
from app.models.user import User
from app.services.job_queue import JobQueue
from tests.factories import make_project

_QUEUE = "/api/v1/ops/queue"
_JOBS = "/api/v1/ops/jobs"


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _email() -> str:
    return f"ops-{uuid.uuid4().hex[:12]}@example.test"


async def _signup(client: AsyncClient) -> tuple[str, uuid.UUID]:
    resp = await client.post(
        "/api/v1/auth/signup", json={"email": _email(), "password": "passw0rd1"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["access_token"], uuid.UUID(body["user"]["id"])


async def _make_operator(app: FastAPI, user_id: uuid.UUID) -> None:
    async with app.state.sessionmaker() as session:
        user = await session.get(User, user_id)
        assert user is not None
        user.is_operator = True
        await session.commit()


class _Seeded:
    def __init__(
        self,
        project_id: uuid.UUID,
        queued: uuid.UUID,
        failed: uuid.UUID,
        stuck: uuid.UUID,
    ) -> None:
        self.project_id = project_id
        self.queued = queued
        self.failed = failed
        self.stuck = stuck


async def _seed_jobs(app: FastAPI) -> _Seeded:
    """One queued, one failed, one stuck-running job in a fresh (foreign) project."""
    async with app.state.sessionmaker() as session:
        project = make_project()
        session.add(project)
        await session.flush()
        queue = JobQueue(session)
        queued = await queue.enqueue(kind=JobKind.RUN, project_id=project.id)

        failed = await queue.enqueue(
            kind=JobKind.RUN, project_id=project.id, max_attempts=1
        )
        await queue.claim(failed.id, worker_id="w")
        await queue.mark_failed_or_retry(failed.id, detail="boom")

        stuck = await queue.enqueue(kind=JobKind.INGEST, project_id=project.id)
        await queue.claim(stuck.id, worker_id="w")  # running
        stuck_row = await queue.get(stuck.id)
        assert stuck_row is not None
        stuck_row.locked_at = datetime.now(UTC) - timedelta(seconds=10_000)
        await session.commit()
        return _Seeded(project.id, queued.id, failed.id, stuck.id)


@pytest_asyncio.fixture
async def operator(
    app_client: tuple[AsyncClient, FastAPI],
) -> tuple[AsyncClient, FastAPI, str]:
    client, app = app_client
    token, user_id = await _signup(client)
    await _make_operator(app, user_id)
    return client, app, token


# --- the gate ---------------------------------------------------------------


async def test_ops_requires_authentication(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    assert (await client.get(_QUEUE)).status_code == 401
    assert (await client.get(_JOBS)).status_code == 401


async def test_non_operator_is_forbidden(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    token, _ = await _signup(client)  # a normal user, not an operator
    assert (await client.get(_QUEUE, headers=_h(token))).status_code == 403
    assert (await client.get(_JOBS, headers=_h(token))).status_code == 403


# --- the snapshot -----------------------------------------------------------


async def test_operator_sees_queue_depth_stuck_and_failed(
    operator: tuple[AsyncClient, FastAPI, str],
) -> None:
    client, app, token = operator
    seeded = await _seed_jobs(app)

    stats = await client.get(_QUEUE, headers=_h(token))
    assert stats.status_code == 200
    body = stats.json()
    assert body["queued"] >= 1  # depth
    assert body["failed"] >= 1
    assert body["running"] >= 1
    assert body["stuck"] >= 1  # the back-dated running job
    assert body["runner_healthy"] is False  # stuck > 0
    assert body["total"] >= 3

    # The failed list reports the failed job (cross-tenant — a project the operator
    # is not a member of).
    failed = (await client.get(f"{_JOBS}?status=failed", headers=_h(token))).json()
    failed_ids = {item["id"] for item in failed["items"]}
    assert str(seeded.failed) in failed_ids
    assert str(seeded.queued) not in failed_ids
    assert all(item["status"] == "failed" for item in failed["items"])


async def test_operator_jobs_list_is_cross_tenant(
    operator: tuple[AsyncClient, FastAPI, str],
) -> None:
    client, app, token = operator
    seeded = await _seed_jobs(app)
    recent = (await client.get(f"{_JOBS}?limit=200", headers=_h(token))).json()
    ids = {item["id"] for item in recent["items"]}
    # All three seeded jobs (a foreign project) are visible to the operator.
    assert {str(seeded.queued), str(seeded.failed), str(seeded.stuck)} <= ids


async def test_operator_can_filter_by_status(
    operator: tuple[AsyncClient, FastAPI, str],
) -> None:
    client, app, token = operator
    await _seed_jobs(app)
    resp = await client.get(f"{_JOBS}?status=queued&limit=200", headers=_h(token))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(item["status"] == JobStatus.QUEUED.value for item in items)
