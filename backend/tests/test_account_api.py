"""GET /account/dashboard — the account-wide overview endpoint (ADR-0065).

Org-scoped: a user only ever sees their own orgs' projects. Covers the empty account,
a project rolled into the health table + status, and the range_days filter bound.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import AsyncClient


async def _new_project(client: AsyncClient, name: str = "T") -> uuid.UUID:
    resp = await client.post("/api/v1/projects", json={"name": name, "repo_url": "/r"})
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


async def test_empty_account_returns_an_empty_dashboard(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    body = (await client.get("/api/v1/account/dashboard")).json()
    assert body["projects_total"] == 0
    assert body["pass_rate"] is None
    assert body["open_findings"]["total"] == 0
    assert body["trend"] == []
    assert body["recent_runs"] == []
    assert body["range_days"] == 30


async def test_dashboard_rolls_up_the_account_projects(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    await _new_project(client, "Alpha")
    await _new_project(client, "Beta")

    body = (await client.get("/api/v1/account/dashboard?range_days=7")).json()
    assert body["range_days"] == 7
    assert body["projects_total"] == 2
    # No runs yet → both projects are "never_run" in the health table.
    assert body["projects_by_status"]["never_run"] == 2
    assert {row["name"] for row in body["project_health"]} == {"Alpha", "Beta"}


async def test_range_days_is_bounded(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    # Out-of-range values are rejected by the query validator (ge=1, le=3650).
    assert (
        await client.get("/api/v1/account/dashboard?range_days=0")
    ).status_code == 422
    assert (
        await client.get("/api/v1/account/dashboard?range_days=99999")
    ).status_code == 422
