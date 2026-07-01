"""The generated-tests viewer API (GET /projects/{id}/tests) — read-only, VIEW-gated.

Lists a project's CURRENT test cases with their runnable code + the human-readable
Brain node each targets, so QA can see what Polaris generated. Hermetic: the project
is created via the API (so the caller owns it), the cases/scripts/nodes are seeded
directly in the shared per-test transaction.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Framework, OracleSource, TestLayer, TestType
from tests.factories import make_node, make_test_case, make_test_script


async def _new_project(client: AsyncClient) -> uuid.UUID:
    resp = await client.post("/api/v1/projects", json={"name": "T", "repo_url": "/r"})
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


async def test_lists_current_tests_with_code_target_and_facets(
    authed_client: tuple[AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = authed_client
    project_id = await _new_project(client)

    node = make_node(project_id, name="GET api/orders")
    db_session.add(node)
    await db_session.flush()
    case = make_test_case(
        project_id,
        type=TestType.HAPPY,
        layer=TestLayer.API,
        oracle_source=OracleSource.CHARACTERIZATION,
        target_node=node.id,
    )
    db_session.add(case)
    await db_session.flush()
    db_session.add(
        make_test_script(
            project_id,
            case.id,
            framework=Framework.PEST,
            code="<?php\nclass Happy_x extends TestCase {}\n",
        )
    )
    await db_session.flush()

    resp = await client.get(f"/api/v1/projects/{project_id}/tests")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 1
    item = data["items"][0]
    # The human-readable target (resolved from the Brain node), the facets, and the
    # actual runnable code the operator wants to read — not a UUID, not empty.
    assert item["target"] == "GET api/orders"
    assert item["type"] == "happy"
    assert item["layer"] == "api"
    assert item["oracle_source"] == "characterization"
    assert item["framework"] == "pest"
    assert "class Happy_x" in item["code"]


async def test_a_case_without_a_target_node_reads_as_a_dash(
    authed_client: tuple[AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    # A case with no target_node (or a since-removed node) must not 500 — it degrades
    # to a dash, and a case with no script yet returns empty code.
    client, _ = authed_client
    project_id = await _new_project(client)
    case = make_test_case(project_id, target_node=None)
    db_session.add(case)
    await db_session.flush()

    resp = await client.get(f"/api/v1/projects/{project_id}/tests")
    assert resp.status_code == 200, resp.text
    item = resp.json()["items"][0]
    assert item["target"] == "—"
    assert item["code"] == ""


async def test_tests_are_scoped_and_view_gated(
    authed_client: tuple[AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    # A non-member can't see (or even confirm) another project's tests — 404, no leak.
    client, _ = authed_client
    project_id = await _new_project(client)
    db_session.add(make_test_case(project_id))
    await db_session.flush()

    outsider = (
        await client.post(
            "/api/v1/auth/signup",
            json={"email": f"o-{uuid.uuid4().hex[:8]}@e.test", "password": "passw0rd1"},
        )
    ).json()["access_token"]
    resp = await client.get(
        f"/api/v1/projects/{project_id}/tests",
        headers={"Authorization": f"Bearer {outsider}"},
    )
    assert resp.status_code == 404
