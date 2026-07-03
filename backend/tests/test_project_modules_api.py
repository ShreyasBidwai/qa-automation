"""GET /projects/{id}/modules — the feature areas a run can be scoped to (ADR-0061).

Derives modules from the Brain's testable targets (endpoints + pages) with per-kind
counts, so the run form can offer a searchable module picker. VIEW-gated, org-scoped.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import NodeKind
from tests.factories import make_node


async def _new_project(client: AsyncClient) -> uuid.UUID:
    resp = await client.post("/api/v1/projects", json={"name": "T", "repo_url": "/r"})
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


async def test_unbuilt_project_has_no_modules(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    project_id = await _new_project(client)
    body = (await client.get(f"/api/v1/projects/{project_id}/modules")).json()
    assert body == {"modules": []}


async def test_modules_are_derived_with_per_kind_counts(
    authed_client: tuple[AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = authed_client
    project_id = await _new_project(client)
    db_session.add_all(
        [
            make_node(project_id, kind=NodeKind.ENDPOINT, name="GET api/v1/orders"),
            make_node(project_id, kind=NodeKind.ENDPOINT, name="POST api/v1/orders"),
            make_node(project_id, kind=NodeKind.PAGE, name="/orders"),
            make_node(project_id, kind=NodeKind.ENDPOINT, name="GET api/v1/users"),
            # A model node is not testable → contributes no module.
            make_node(project_id, kind=NodeKind.MODEL, name="Order"),
        ]
    )
    await db_session.flush()

    resp = await client.get(f"/api/v1/projects/{project_id}/modules")
    assert resp.status_code == 200, resp.text
    modules = resp.json()["modules"]
    assert [m["key"] for m in modules] == ["orders", "users"]  # most targets first
    orders = modules[0]
    assert orders == {
        "key": "orders",
        "label": "Orders",
        "endpoint_count": 2,
        "page_count": 1,
        "total": 3,
    }


async def test_modules_are_view_gated_no_leak(
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
        f"/api/v1/projects/{project_id}/modules",
        headers={"Authorization": f"Bearer {outsider}"},
    )
    assert resp.status_code == 404
