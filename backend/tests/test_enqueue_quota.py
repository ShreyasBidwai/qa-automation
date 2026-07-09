"""The enqueue gate (ADR-0068 suspension + ADR-0069 run quota): a suspended org and an
org that has exhausted its plan's monthly run credits cannot start runs/ingests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.plan import Plan
from app.models.user import User
from app.repositories.organization_repository import OrganizationRepository

_RUN = {"mode": "mode_b", "strategy": "full_sweep"}


async def _signup(client: httpx.AsyncClient) -> tuple[dict[str, str], str]:
    email = f"quota-{uuid.uuid4().hex[:10]}@e.test"
    token = (
        await client.post(
            "/api/v1/auth/signup", json={"email": email, "password": "quotapass1"}
        )
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, email


async def _project(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects", json={"name": "Q", "repo_url": "/r"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _org_for(session: AsyncSession, email: str) -> Organization:
    user = (await session.scalars(select(User).where(User.email == email))).one()
    org = await OrganizationRepository(session).get_personal_org(user.id)
    assert org is not None
    return org


async def test_suspended_org_cannot_run_or_ingest(
    app_client: tuple[httpx.AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = app_client
    headers, email = await _signup(client)
    pid = await _project(client, headers)
    org = await _org_for(db_session, email)
    org.suspended_at = datetime.now(UTC)
    await db_session.flush()

    run = await client.post(f"/api/v1/projects/{pid}/runs", json=_RUN, headers=headers)
    assert run.status_code == 403
    ingest = await client.post(f"/api/v1/projects/{pid}/ingest", headers=headers)
    assert ingest.status_code == 403


async def test_run_quota_blocks_when_monthly_credits_exhausted(
    app_client: tuple[httpx.AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = app_client
    headers, email = await _signup(client)
    pid = await _project(client, headers)
    # Put the org on a 1-run/month plan.
    db_session.add(
        Plan(
            key="tiny",
            name="Tiny",
            included_run_credits_monthly=1,
            max_parallelism=1,
            retention_days=1,
        )
    )
    org = await _org_for(db_session, email)
    org.plan_key = "tiny"
    await db_session.flush()

    # The first run consumes the single credit; the second is over quota (402).
    first = await client.post(f"/api/v1/projects/{pid}/runs", json=_RUN, headers=headers)
    assert first.status_code == 202
    second = await client.post(
        f"/api/v1/projects/{pid}/runs", json=_RUN, headers=headers
    )
    assert second.status_code == 402


async def test_free_plan_allows_a_run(
    app_client: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    headers, _ = await _signup(client)
    pid = await _project(client, headers)
    # Default free plan (50 credits/mo) — a first run is well within quota.
    run = await client.post(f"/api/v1/projects/{pid}/runs", json=_RUN, headers=headers)
    assert run.status_code == 202
