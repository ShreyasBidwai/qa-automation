"""Run preferences on the recent-runs list + one-click re-run (ADR-0062).

A run's id equals its job's id, so each listed run carries the choices it was started
with (from the durable job payload); ``POST /runs/{id}/rerun`` copies that payload
verbatim into a fresh run — a faithful re-run without re-entering the options.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobKind, RunMode
from app.services.job_queue import JobQueue
from tests.factories import make_run

_PREFS = {
    "mode": "mode_b",
    "strategy": "full_sweep",
    "changeset": [],
    "max_targets": 50,
    "prompt": None,
    "layers": ["api"],
    "modules": ["orders"],
    "layer": None,
}


async def _new_project(client: AsyncClient) -> uuid.UUID:
    resp = await client.post("/api/v1/projects", json={"name": "T", "repo_url": "/r"})
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


async def _seed_run(
    session: AsyncSession, project_id: uuid.UUID, payload: dict[str, object]
) -> uuid.UUID:
    # A run row is created with the job's id (ADR-0036); mirror that so the list
    # endpoint can attach preferences by looking the job up by run id.
    job = await JobQueue(session).enqueue(
        kind=JobKind.RUN, project_id=project_id, mode="mode_b", payload=payload
    )
    session.add(
        make_run(
            project_id, id=job.id, mode=RunMode.B, status="succeeded", run_number=1
        )
    )
    await session.flush()
    return job.id


async def test_recent_runs_expose_their_preferences(
    authed_client: tuple[AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = authed_client
    project_id = await _new_project(client)
    await _seed_run(db_session, project_id, _PREFS)

    body = (await client.get(f"/api/v1/projects/{project_id}/runs")).json()
    assert body["items"][0]["preferences"] == {
        "mode": "mode_b",
        "strategy": "full_sweep",
        "layers": ["api"],
        "modules": ["orders"],
        "changeset_size": None,
        "layer": None,
    }


async def test_rerun_copies_the_preferences_into_a_fresh_run(
    authed_client: tuple[AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = authed_client
    project_id = await _new_project(client)
    original = await _seed_run(db_session, project_id, _PREFS)

    resp = await client.post(f"/api/v1/runs/{original}/rerun")
    assert resp.status_code == 202, resp.text
    new_run_id = uuid.UUID(resp.json()["run_id"])
    assert new_run_id != original

    # The new run's job holds the SAME preferences, verbatim.
    new_job = await JobQueue(db_session).get(new_run_id)
    assert new_job is not None
    assert new_job.payload == _PREFS
    assert new_job.project_id == project_id


async def test_rerun_is_run_gated_no_leak(
    authed_client: tuple[AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = authed_client
    project_id = await _new_project(client)
    run_id = await _seed_run(db_session, project_id, _PREFS)

    outsider = (
        await client.post(
            "/api/v1/auth/signup",
            json={"email": f"o-{uuid.uuid4().hex[:8]}@e.test", "password": "passw0rd1"},
        )
    ).json()["access_token"]
    resp = await client.post(
        f"/api/v1/runs/{run_id}/rerun",
        headers={"Authorization": f"Bearer {outsider}"},
    )
    assert resp.status_code == 404
