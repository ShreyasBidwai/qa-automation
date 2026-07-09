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
from tests.factories import (
    make_node,
    make_result,
    make_run,
    make_test_case,
    make_test_script,
)


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


async def test_target_falls_back_to_case_key_when_the_node_is_unset(
    authed_client: tuple[AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    # Generated cases usually carry their target in case_key ("METHOD path::type::…"),
    # not target_node — so the viewer must read the target from the key, else every
    # row would show a useless dash.
    client, _ = authed_client
    project_id = await _new_project(client)
    case = make_test_case(
        project_id, target_node=None, case_key="GET /orders::happy::happy"
    )
    db_session.add(case)
    await db_session.flush()

    resp = await client.get(f"/api/v1/projects/{project_id}/tests")
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"][0]["target"] == "GET /orders"


async def test_a_case_with_no_target_at_all_reads_as_a_dash(
    authed_client: tuple[AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    # No node AND no case_key must not 500 — it degrades to a dash, and a case with
    # no script yet returns empty code.
    client, _ = authed_client
    project_id = await _new_project(client)
    case = make_test_case(project_id, target_node=None, case_key=None)
    db_session.add(case)
    await db_session.flush()

    resp = await client.get(f"/api/v1/projects/{project_id}/tests")
    assert resp.status_code == 200, resp.text
    item = resp.json()["items"][0]
    assert item["target"] == "—"
    assert item["code"] == ""


async def test_tests_can_be_scoped_to_a_single_run(
    authed_client: tuple[AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    # `?run=` narrows the viewer to the exact tests that run exercised (its Results),
    # so a module-scoped run shows only its tests — not the whole project's.
    client, _ = authed_client
    project_id = await _new_project(client)
    in_run = make_test_case(project_id, case_key="GET /orders::happy::happy")
    other = make_test_case(project_id, case_key="GET /users::happy::happy")
    db_session.add_all([in_run, other])
    await db_session.flush()
    run = make_run(project_id, status="succeeded", run_number=1)
    db_session.add(run)
    await db_session.flush()
    db_session.add(make_result(project_id, run.id, in_run.id))
    await db_session.flush()

    all_tests = (await client.get(f"/api/v1/projects/{project_id}/tests")).json()
    assert all_tests["total"] == 2  # unscoped = the whole project

    scoped = (
        await client.get(f"/api/v1/projects/{project_id}/tests?run={run.id}")
    ).json()
    assert scoped["total"] == 1
    assert scoped["items"][0]["target"] == "GET /orders"

    # A run id from outside the project yields nothing (project-scoped, no leak).
    empty = (
        await client.get(f"/api/v1/projects/{project_id}/tests?run={uuid.uuid4()}")
    ).json()
    assert empty["total"] == 0


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
