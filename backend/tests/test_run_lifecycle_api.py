"""Run lifecycle API: cancel a run (DELETE /runs/{id}) and the CI/PR gate verdict
(GET /runs/{id}/ci). architecture-review DO-NEXT #7 + DO-FIRST #5.
"""

from __future__ import annotations

import uuid

import httpx
from fastapi import FastAPI

from app.services.job_queue import JobQueue


async def _auth_project(client: httpx.AsyncClient) -> tuple[dict[str, str], str]:
    email = f"life-{uuid.uuid4().hex[:10]}@e.test"
    token = (
        await client.post(
            "/api/v1/auth/signup", json={"email": email, "password": "lifecyclepw1"}
        )
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    pid = (
        await client.post(
            "/api/v1/projects", json={"name": "Life", "repo_url": "/r"}, headers=headers
        )
    ).json()["id"]
    return headers, pid


_RUN = {"mode": "mode_b", "strategy": "full_sweep"}


async def _new_run(client: httpx.AsyncClient, headers: dict[str, str], pid: str) -> str:
    resp = await client.post(
        f"/api/v1/projects/{pid}/runs", json=_RUN, headers=headers
    )
    assert resp.status_code == 202, resp.text
    return resp.json()["run_id"]


async def test_cancel_queued_run(
    app_client: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    headers, pid = await _auth_project(client)
    rid = await _new_run(client, headers, pid)

    cancel = await client.delete(f"/api/v1/runs/{rid}", headers=headers)
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    got = await client.get(f"/api/v1/runs/{rid}", headers=headers)
    assert got.json()["status"] == "cancelled"


async def test_cancel_is_rbac_gated(
    app_client: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    headers, pid = await _auth_project(client)
    rid = await _new_run(client, headers, pid)
    outsider = (
        await client.post(
            "/api/v1/auth/signup",
            json={"email": f"o-{uuid.uuid4().hex[:8]}@e.test", "password": "passw0rd1"},
        )
    ).json()["access_token"]
    resp = await client.delete(
        f"/api/v1/runs/{rid}", headers={"Authorization": f"Bearer {outsider}"}
    )
    assert resp.status_code == 404  # not a member → existence not leaked


async def test_ci_summary_pending_then_pass(
    app_client: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, app = app_client
    headers, pid = await _auth_project(client)
    rid = await _new_run(client, headers, pid)

    # Queued → the gate is pending (don't block the pipeline yet).
    ci = (await client.get(f"/api/v1/runs/{rid}/ci", headers=headers)).json()
    assert ci["terminal"] is False and ci["gate"] == "pending"

    # Drive it to succeeded with no findings → the gate passes.
    async with app.state.sessionmaker() as session:
        queue = JobQueue(session)
        await queue.claim(uuid.UUID(rid), worker_id="ci-test")
        await queue.mark_succeeded(uuid.UUID(rid), run_id=uuid.UUID(rid), summary={})
        await session.commit()

    ci = (await client.get(f"/api/v1/runs/{rid}/ci", headers=headers)).json()
    assert ci["terminal"] is True
    assert ci["gate"] == "pass"
    assert ci["critical"] == 0 and ci["major"] == 0


async def test_ci_summary_fails_on_a_failed_run(
    app_client: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, app = app_client
    headers, pid = await _auth_project(client)
    rid = await _new_run(client, headers, pid)

    async with app.state.sessionmaker() as session:
        queue = JobQueue(session)
        await queue.claim(uuid.UUID(rid), worker_id="ci-test")
        await queue.mark_failed_or_retry(
            uuid.UUID(rid), detail="boom", terminal=True
        )
        await session.commit()

    ci = (await client.get(f"/api/v1/runs/{rid}/ci", headers=headers)).json()
    assert ci["terminal"] is True and ci["gate"] == "fail"
