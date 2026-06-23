"""List endpoints (GET /projects, GET /projects/{id}/runs) — fast API tests.

Seeds via the app's committed sessionmaker (the GET endpoints read through their
own request session, so data must be committed) with explicit timestamps for a
deterministic newest-first order. The projects list is global, so its tests clear
the table first; the runs list is project-scoped and needs no clear.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text

from app.models.enums import FindingLayer, OracleSource, Outcome, RunMode
from app.models.finding import Finding
from tests.factories import make_project, make_result, make_run, make_test_case

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


async def _clear_projects(app: FastAPI) -> None:
    async with app.state.sessionmaker() as session:
        await session.execute(text("DELETE FROM projects"))
        await session.commit()


async def _personal_org_id(client: AsyncClient) -> uuid.UUID:
    """The authed user's personal org — projects must live in an org they're in
    (B3, ADR-0032/0033) for the list/run endpoints to return them."""
    body = (await client.get("/api/v1/orgs")).json()
    for org in body["items"]:
        if org["is_personal"]:
            return uuid.UUID(org["id"])
    raise AssertionError("authed user has no personal org")


async def _seed_project(
    app: FastAPI, *, name: str, hour: int, org_id: uuid.UUID
) -> uuid.UUID:
    async with app.state.sessionmaker() as session:
        project = make_project(
            name=name, org_id=org_id, created_at=_BASE + timedelta(hours=hour)
        )
        session.add(project)
        await session.flush()
        project_id = project.id
        await session.commit()
        return project_id


async def _seed_run(
    app: FastAPI,
    project_id: uuid.UUID,
    *,
    hour: int,
    mode: RunMode = RunMode.B,
    status: str = "passed",
    outcomes: Sequence[Outcome] = (),
) -> uuid.UUID:
    async with app.state.sessionmaker() as session:
        run = make_run(
            project_id,
            mode=mode,
            status=status,
            created_at=_BASE + timedelta(hours=hour),
        )
        session.add(run)
        await session.flush()
        if outcomes:
            case = make_test_case(project_id)
            session.add(case)
            await session.flush()
            for outcome in outcomes:
                session.add(make_result(project_id, run.id, case.id, outcome=outcome))
        run_id = run.id
        await session.commit()
        return run_id


async def _seed_open_finding(
    app: FastAPI, project_id: uuid.UUID, run_id: uuid.UUID, *, key: str
) -> None:
    async with app.state.sessionmaker() as session:
        case = make_test_case(project_id)
        session.add(case)
        await session.flush()
        result = make_result(project_id, run_id, case.id, outcome=Outcome.FAIL)
        session.add(result)
        await session.flush()
        session.add(
            Finding(
                project_id=project_id,
                run_id=run_id,
                result_id=result.id,
                root_cause_key=key,
                explains_count=1,
                title=f"finding {key}",
                layer=FindingLayer.API,
                oracle_source=OracleSource.RULE_DERIVED,
                confidence_mixed=False,
                expected={},
                location={},
                severity="major",
                status="new",
            )
        )
        await session.commit()


# --- projects list ----------------------------------------------------------


async def test_list_projects_empty(authed_client: tuple[AsyncClient, FastAPI]) -> None:
    client, app = authed_client
    await _clear_projects(app)

    resp = await client.get("/api/v1/projects")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_list_projects_newest_first(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    await _clear_projects(app)
    org_id = await _personal_org_id(client)
    await _seed_project(app, name="Alpha", hour=1, org_id=org_id)
    await _seed_project(app, name="Beta", hour=2, org_id=org_id)
    await _seed_project(app, name="Gamma", hour=3, org_id=org_id)

    body = (await client.get("/api/v1/projects")).json()
    assert [item["name"] for item in body["items"]] == ["Gamma", "Beta", "Alpha"]
    assert body["total"] == 3


async def test_list_projects_pagination_and_bounds(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    await _clear_projects(app)
    org_id = await _personal_org_id(client)
    for hour, name in [(1, "P1"), (2, "P2"), (3, "P3")]:
        await _seed_project(app, name=name, hour=hour, org_id=org_id)

    page1 = (await client.get("/api/v1/projects?limit=2")).json()
    assert [item["name"] for item in page1["items"]] == ["P3", "P2"]
    assert (page1["total"], page1["limit"], page1["offset"]) == (3, 2, 0)

    page2 = (await client.get("/api/v1/projects?limit=2&offset=2")).json()
    assert [item["name"] for item in page2["items"]] == ["P1"]

    # Out-of-range limits are rejected (bounded).
    assert (await client.get("/api/v1/projects?limit=0")).status_code == 422
    assert (await client.get("/api/v1/projects?limit=101")).status_code == 422
    assert (await client.get("/api/v1/projects?offset=-1")).status_code == 422


async def test_list_projects_carries_enriched_summary_fields(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    await _clear_projects(app)
    org_id = await _personal_org_id(client)

    # Project WITH a run (failed, 2/3 pass) + an open finding.
    async with app.state.sessionmaker() as session:
        active = make_project(
            name="Active",
            org_id=org_id,
            created_at=_BASE + timedelta(hours=2),
            settings={"repo_url": "https://git/active.git", "stack": "laravel"},
        )
        session.add(active)
        await session.flush()
        active_id = active.id
        await session.commit()
    run_id = await _seed_run(
        app,
        active_id,
        hour=5,
        status="failed",
        outcomes=(Outcome.PASS, Outcome.PASS),
    )
    # The finding contributes the run's one FAIL result → 2 pass / 3 total = 0.6667.
    await _seed_open_finding(app, active_id, run_id, key="BUG#fail")

    # Project with NO runs (degrades to defaults).
    await _seed_project(app, name="Fresh", hour=1, org_id=org_id)

    items = {
        item["name"]: item
        for item in (await client.get("/api/v1/projects")).json()["items"]
    }

    active_item = items["Active"]
    assert active_item["stack"] == "laravel"
    assert active_item["status"] == "action_needed"  # has open findings
    assert active_item["open_findings_count"] == 1
    assert active_item["last_run"]["run_id"] == str(run_id)
    assert active_item["last_run"]["status"] == "failed"
    assert active_item["last_run"]["mode"] == "B"
    assert active_item["last_run"]["pass_rate"] == 0.6667
    # Existing fields remain (additive contract).
    assert active_item["repo_url"] == "https://git/active.git"
    assert "created_at" in active_item

    fresh_item = items["Fresh"]
    assert fresh_item["last_run"] is None
    assert fresh_item["status"] == "never_run"
    assert fresh_item["open_findings_count"] == 0
    assert fresh_item["stack"] is None


# --- runs list --------------------------------------------------------------


async def test_list_project_runs_newest_first_and_scoped(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    org_id = await _personal_org_id(client)
    project_a = await _seed_project(app, name="A", hour=1, org_id=org_id)
    project_b = await _seed_project(app, name="B", hour=1, org_id=org_id)
    r1 = await _seed_run(app, project_a, hour=1)
    r2 = await _seed_run(app, project_a, hour=2)
    r3 = await _seed_run(app, project_a, hour=3)
    await _seed_run(app, project_b, hour=5)  # another project's run

    body = (await client.get(f"/api/v1/projects/{project_a}/runs")).json()
    assert [item["id"] for item in body["items"]] == [str(r3), str(r2), str(r1)]
    assert body["total"] == 3
    assert body["items"][0]["mode"] == "B"

    # Project B sees only its own run — no cross-project leakage.
    body_b = (await client.get(f"/api/v1/projects/{project_b}/runs")).json()
    assert body_b["total"] == 1
    assert body_b["items"][0]["id"] not in {str(r1), str(r2), str(r3)}


async def test_list_project_runs_unknown_project_is_404(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    resp = await client.get(f"/api/v1/projects/{uuid.uuid4()}/runs")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")


async def test_list_project_runs_pass_rate(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    org_id = await _personal_org_id(client)
    project_id = await _seed_project(app, name="PR", hour=1, org_id=org_id)
    scored = await _seed_run(
        app, project_id, hour=2, outcomes=[Outcome.PASS, Outcome.PASS, Outcome.FAIL]
    )
    unscored = await _seed_run(app, project_id, hour=1)  # no results

    items = {
        item["id"]: item
        for item in (await client.get(f"/api/v1/projects/{project_id}/runs")).json()[
            "items"
        ]
    }
    assert items[str(scored)]["pass_rate"] == 0.6667
    assert items[str(unscored)]["pass_rate"] is None


async def test_list_project_runs_pagination(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    org_id = await _personal_org_id(client)
    project_id = await _seed_project(app, name="Pager", hour=1, org_id=org_id)
    r1 = await _seed_run(app, project_id, hour=1)
    r2 = await _seed_run(app, project_id, hour=2)
    r3 = await _seed_run(app, project_id, hour=3)

    page1 = (await client.get(f"/api/v1/projects/{project_id}/runs?limit=2")).json()
    assert [item["id"] for item in page1["items"]] == [str(r3), str(r2)]
    assert page1["total"] == 3

    page2 = (
        await client.get(f"/api/v1/projects/{project_id}/runs?limit=2&offset=2")
    ).json()
    assert [item["id"] for item in page2["items"]] == [str(r1)]
