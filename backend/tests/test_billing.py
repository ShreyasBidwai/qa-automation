"""Customer plan catalog (ADR-0069): GET /plans lists the public tiers (authenticated)."""

from __future__ import annotations

import uuid

import httpx
from fastapi import FastAPI


async def _headers(client: httpx.AsyncClient) -> dict[str, str]:
    email = f"plans-{uuid.uuid4().hex[:10]}@e.test"
    token = (
        await client.post(
            "/api/v1/auth/signup", json={"email": email, "password": "planspass1"}
        )
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def test_list_plans_requires_auth(
    app_client: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    assert (await client.get("/api/v1/plans")).status_code == 401


async def test_list_plans_returns_the_public_catalog(
    app_client: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    headers = await _headers(client)
    body = (await client.get("/api/v1/plans", headers=headers)).json()
    keys = {plan["key"] for plan in body["items"]}
    assert {"free", "team", "business", "enterprise"} <= keys

    free = next(plan for plan in body["items"] if plan["key"] == "free")
    assert free["price_per_seat_monthly_usd"] == 0
    enterprise = next(plan for plan in body["items"] if plan["key"] == "enterprise")
    assert enterprise["price_per_seat_monthly_usd"] is None  # custom / contact us
    assert enterprise["max_projects"] is None  # unlimited
    assert enterprise["features"].get("saml") is True
