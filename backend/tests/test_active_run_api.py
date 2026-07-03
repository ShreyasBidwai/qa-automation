"""GET /runs/active — the caller's current in-progress run (the "Ongoing run" view).

Returns the newest still-active (queued/running) RUN job across the user's projects,
or an all-null response when none. Org-scoped: it never surfaces another tenant's run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.job_queue import JobQueue

_RUN = {"mode": "mode_b", "strategy": "full_sweep"}


async def _signup(client: httpx.AsyncClient) -> dict[str, str]:
    email = f"active-{uuid.uuid4().hex[:10]}@e.test"
    token = (
        await client.post(
            "/api/v1/auth/signup", json={"email": email, "password": "activerunpw1"}
        )
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _project(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects", json={"name": "Act", "repo_url": "/r"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _new_run(client: httpx.AsyncClient, headers: dict[str, str], pid: str) -> str:
    resp = await client.post(f"/api/v1/projects/{pid}/runs", json=_RUN, headers=headers)
    assert resp.status_code == 202, resp.text
    return resp.json()["run_id"]


async def test_returns_the_users_active_run(
    app_client: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    headers = await _signup(client)
    pid = await _project(client, headers)
    run_id = await _new_run(client, headers, pid)

    resp = await client.get("/api/v1/runs/active", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"] == run_id
    assert body["project_id"] == pid
    assert body["mode"] == "mode_b"
    assert body["status"] == "queued"


async def test_no_active_run_returns_nulls(
    app_client: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    headers = await _signup(client)
    await _project(client, headers)  # a project, but no run started

    body = (await client.get("/api/v1/runs/active", headers=headers)).json()
    assert body == {"run_id": None, "project_id": None, "mode": None, "status": None}


async def test_returns_the_newest_active_run(
    app_client: tuple[httpx.AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = app_client
    headers = await _signup(client)
    pid = await _project(client, headers)
    older = await _new_run(client, headers, pid)
    newest = await _new_run(client, headers, pid)

    # The one wrapping test transaction stamps both jobs with the same func.now()
    # created_at (in production each run is a separate transaction with a distinct
    # timestamp), so pin distinct times to exercise the "newest wins" ordering.
    queue = JobQueue(db_session)
    older_job = await queue.get(uuid.UUID(older))
    newest_job = await queue.get(uuid.UUID(newest))
    assert older_job is not None and newest_job is not None
    older_job.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    newest_job.created_at = datetime(2026, 1, 2, tzinfo=UTC)
    await db_session.flush()

    body = (await client.get("/api/v1/runs/active", headers=headers)).json()
    assert body["run_id"] == newest


async def test_active_run_is_org_scoped_no_leak(
    app_client: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    # One user's in-progress run must never appear in another user's Ongoing view.
    client, _ = app_client
    owner = await _signup(client)
    pid = await _project(client, owner)
    await _new_run(client, owner, pid)

    outsider = await _signup(client)
    body = (await client.get("/api/v1/runs/active", headers=outsider)).json()
    assert body["run_id"] is None
