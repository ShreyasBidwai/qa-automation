"""GET /projects/{id}/model — the built-model (Brain) summary for the Project view.

Reports whether the model is built, how many nodes/edges, the per-kind breakdown, and
when it was last built. VIEW-gated and org-scoped (a non-member gets 404, no leak).
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import NodeKind
from tests.factories import make_edge, make_node


async def _new_project(client: AsyncClient) -> uuid.UUID:
    resp = await client.post("/api/v1/projects", json={"name": "T", "repo_url": "/r"})
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


async def test_unbuilt_model_reports_not_built(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    project_id = await _new_project(client)

    body = (await client.get(f"/api/v1/projects/{project_id}/model")).json()
    assert body == {
        "built": False,
        "node_count": 0,
        "edge_count": 0,
        "nodes_by_kind": [],
        "last_built_at": None,
    }


async def test_built_model_reports_counts_and_kinds(
    authed_client: tuple[AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = authed_client
    project_id = await _new_project(client)

    a = make_node(project_id, kind=NodeKind.ENDPOINT, name="GET api/orders")
    b = make_node(project_id, kind=NodeKind.ENDPOINT, name="POST api/orders")
    page = make_node(project_id, kind=NodeKind.PAGE, name="/orders")
    db_session.add_all([a, b, page])
    await db_session.flush()
    db_session.add(make_edge(project_id, a.id, b.id))
    await db_session.flush()

    resp = await client.get(f"/api/v1/projects/{project_id}/model")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["built"] is True
    assert body["node_count"] == 3
    assert body["edge_count"] == 1
    # Most-numerous kind leads: 2 endpoints before 1 page.
    assert body["nodes_by_kind"] == [
        {"kind": "endpoint", "count": 2},
        {"kind": "page", "count": 1},
    ]
    assert body["last_built_at"] is not None


async def test_model_is_view_gated_no_leak(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    project_id = await _new_project(client)
    outsider = (
        await client.post(
            "/api/v1/auth/signup",
            json={"email": f"o-{uuid.uuid4().hex[:8]}@e.test", "password": "passw0rd1"},
        )
    ).json()["access_token"]
    resp = await client.get(
        f"/api/v1/projects/{project_id}/model",
        headers={"Authorization": f"Bearer {outsider}"},
    )
    assert resp.status_code == 404
