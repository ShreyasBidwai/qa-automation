"""GET /api/v1/search — the ⌘K command palette endpoint (ADR-0068).

Seeds projects via the real API (so they land in the authed user's actual personal
org) and findings/runs via the app's committed sessionmaker (mirrors
tests/test_api_lists.py — the endpoint reads through its own request session, so
seeded data must be committed, not just flushed).
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import AsyncClient

from app.models.enums import FindingLayer, OracleSource, Outcome, RunMode, RunTrigger
from app.models.finding import Finding
from app.models.run import Run
from tests.factories import make_result, make_test_case


async def _new_project(client: AsyncClient, name: str) -> uuid.UUID:
    resp = await client.post(
        "/api/v1/projects", json={"name": name, "repo_url": "/r"}
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


async def _seed_run(app: FastAPI, project_id: uuid.UUID, **overrides: object) -> uuid.UUID:
    async with app.state.sessionmaker() as session:
        attrs: dict[str, object] = {
            "project_id": project_id,
            "trigger": RunTrigger.MANUAL,
            "mode": RunMode.C,
            "status": "passed",
        }
        attrs.update(overrides)
        run = Run(**attrs)
        session.add(run)
        await session.flush()
        run_id = run.id
        await session.commit()
        return run_id


async def _seed_finding(
    app: FastAPI, project_id: uuid.UUID, run_id: uuid.UUID, title: str
) -> uuid.UUID:
    async with app.state.sessionmaker() as session:
        case = make_test_case(project_id, oracle_source=OracleSource.RULE_DERIVED)
        session.add(case)
        await session.flush()
        result = make_result(project_id, run_id, case.id, outcome=Outcome.FAIL)
        session.add(result)
        await session.flush()
        finding = Finding(
            project_id=project_id,
            run_id=run_id,
            result_id=result.id,
            root_cause_key=f"key-{uuid.uuid4().hex[:8]}",
            explains_count=1,
            title=title,
            layer=FindingLayer.API,
            oracle_source=OracleSource.RULE_DERIVED,
            confidence_mixed=False,
            expected={},
            location={},
            severity="major",
            status="new",
        )
        session.add(finding)
        await session.flush()
        finding_id = finding.id
        await session.commit()
        return finding_id


async def test_finds_project_by_partial_case_insensitive_name(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    await _new_project(client, "Checkout Service")

    resp = await client.get("/api/v1/search", params={"q": "checkout"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "checkout"
    assert any(
        item["type"] == "project" and item["label"] == "Checkout Service"
        for item in body["items"]
    )


async def test_finds_finding_by_title(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    project_id = await _new_project(client, "Orders API")
    run_id = await _seed_run(app, project_id)
    await _seed_finding(app, project_id, run_id, "Checkout returns 500")

    resp = await client.get("/api/v1/search", params={"q": "500"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert any(
        item["type"] == "finding" and item["label"] == "Checkout returns 500"
        for item in items
    )


async def test_finds_run_by_project_name(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    project_id = await _new_project(client, "Widgets Frontend")
    run_id = await _seed_run(app, project_id, run_number=7)

    resp = await client.get("/api/v1/search", params={"q": "Widgets Frontend"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    run_items = [item for item in items if item["type"] == "run"]
    assert run_items, items
    assert run_items[0]["id"] == str(run_id)
    assert run_items[0]["url"] == f"/runs/{run_id}/findings"
    assert "Widgets Frontend" in run_items[0]["label"]


async def test_blank_query_returns_no_rows(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    await _new_project(client, "Anything At All")

    resp = await client.get("/api/v1/search")
    assert resp.status_code == 200
    assert resp.json() == {"query": "", "items": []}


async def test_types_filter_narrows_to_the_requested_kind(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    project_id = await _new_project(client, "Payments Gateway")
    run_id = await _seed_run(app, project_id)
    await _seed_finding(app, project_id, run_id, "Payments Gateway timeout")

    resp = await client.get(
        "/api/v1/search", params={"q": "Payments Gateway", "types": "project"}
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items and all(item["type"] == "project" for item in items)


async def test_unknown_type_is_rejected(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    resp = await client.get(
        "/api/v1/search", params={"q": "x", "types": "project,bogus"}
    )
    assert resp.status_code == 422


async def test_q_over_max_length_is_rejected(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    resp = await client.get("/api/v1/search", params={"q": "x" * 101})
    assert resp.status_code == 422


async def test_limit_bounds_results_per_type(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    for i in range(5):
        await _new_project(client, f"Bounded Project {i}")

    resp = await client.get(
        "/api/v1/search",
        params={"q": "Bounded Project", "types": "project", "limit": 2},
    )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2


async def test_cross_org_isolation_no_leak(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    """A user with no shared org must never see another org's rows (ADR-0033)."""
    client, app = authed_client
    await _new_project(client, "SecretProjectXYZ")

    outsider_email = f"outsider-{uuid.uuid4().hex[:12]}@example.test"
    signup = await client.post(
        "/api/v1/auth/signup",
        json={"email": outsider_email, "password": "outsiderpw1"},
    )
    assert signup.status_code == 201, signup.text
    outsider_token = signup.json()["access_token"]

    resp = await client.get(
        "/api/v1/search",
        params={"q": "SecretProjectXYZ"},
        headers={"Authorization": f"Bearer {outsider_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []
