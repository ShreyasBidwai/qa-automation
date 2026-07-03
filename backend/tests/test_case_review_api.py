"""Accept/discard a pending authored proposal (POST …/tests/{id}/accept|/discard).

Describe-it (UI/API) and CSV author cases as PENDING proposals; a human accepts them
(they stay current + run) or discards them (they drop from the viewer + never run).
MANAGE_PROJECT; a non-proposal or another project's case is a 404 (no leak).
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import CaseOrigin, ProposalStatus
from tests.factories import make_test_case


async def _new_project(client: AsyncClient) -> uuid.UUID:
    resp = await client.post("/api/v1/projects", json={"name": "T", "repo_url": "/r"})
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


async def _pending_case(
    db_session: AsyncSession, project_id: uuid.UUID
) -> uuid.UUID:
    case = make_test_case(
        project_id,
        origin=CaseOrigin.PROPOSED,
        proposal_status=ProposalStatus.PENDING,
    )
    db_session.add(case)
    await db_session.flush()
    return case.id


async def test_accept_keeps_the_case_current_and_marks_it_accepted(
    authed_client: tuple[AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = authed_client
    project_id = await _new_project(client)
    case_id = await _pending_case(db_session, project_id)

    resp = await client.post(f"/api/v1/projects/{project_id}/tests/{case_id}/accept")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "id": str(case_id),
        "proposal_status": "accepted",
        "is_current": True,
    }
    # Still listed, now flagged accepted — it will run from here on.
    listing = (await client.get(f"/api/v1/projects/{project_id}/tests")).json()
    assert listing["total"] == 1
    assert listing["items"][0]["origin"] == "proposed"
    assert listing["items"][0]["proposal_status"] == "accepted"


async def test_discard_drops_the_case_from_the_viewer(
    authed_client: tuple[AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = authed_client
    project_id = await _new_project(client)
    case_id = await _pending_case(db_session, project_id)

    resp = await client.post(f"/api/v1/projects/{project_id}/tests/{case_id}/discard")
    assert resp.status_code == 200, resp.text
    assert resp.json()["proposal_status"] == "rejected"
    assert resp.json()["is_current"] is False
    # No longer current → gone from the viewer (and from run selection).
    listing = (await client.get(f"/api/v1/projects/{project_id}/tests")).json()
    assert listing["total"] == 0


async def test_reviewing_a_non_proposal_is_404(
    authed_client: tuple[AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    # A plain generated case (no pending proposal) is not a reviewable resource; and
    # re-accepting an already-resolved case must not silently mutate it.
    client, _ = authed_client
    project_id = await _new_project(client)
    plain = make_test_case(project_id, origin=CaseOrigin.GENERATED)
    db_session.add(plain)
    await db_session.flush()

    resp = await client.post(
        f"/api/v1/projects/{project_id}/tests/{plain.id}/accept"
    )
    assert resp.status_code == 404

    # Accept a real proposal, then a second accept is a 404 (already resolved).
    case_id = await _pending_case(db_session, project_id)
    assert (
        await client.post(f"/api/v1/projects/{project_id}/tests/{case_id}/accept")
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/projects/{project_id}/tests/{case_id}/accept")
    ).status_code == 404


async def test_review_is_manage_gated_no_leak_to_outsiders(
    authed_client: tuple[AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = authed_client
    project_id = await _new_project(client)
    case_id = await _pending_case(db_session, project_id)

    outsider = (
        await client.post(
            "/api/v1/auth/signup",
            json={"email": f"o-{uuid.uuid4().hex[:8]}@e.test", "password": "passw0rd1"},
        )
    ).json()["access_token"]
    resp = await client.post(
        f"/api/v1/projects/{project_id}/tests/{case_id}/discard",
        headers={"Authorization": f"Bearer {outsider}"},
    )
    assert resp.status_code == 404
