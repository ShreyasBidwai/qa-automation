"""Liveness/readiness behavior (Standards §9, §15).

Asserts the contract: /readyz is 200 only when the app has started AND the
database is reachable; otherwise 503. /healthz is liveness-only.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.state import app_state


async def test_healthz_is_always_ok(
    app_client: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, _app = app_client
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_is_ready_when_database_up(
    app_client: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, _app = app_client
    response = await client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "up"


async def test_readyz_is_503_before_startup_completes(
    app_client: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, _app = app_client
    # Simulate "not started / draining": readiness must fail even though the DB
    # is reachable, proving the readiness gate (not just the DB check).
    app_state.is_ready = False
    try:
        response = await client.get("/readyz")
    finally:
        app_state.is_ready = True
    assert response.status_code == 503
    assert response.json()["status"] == "not-ready"


async def test_readyz_is_503_when_database_unreachable(
    app_client: tuple[httpx.AsyncClient, FastAPI],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, app = app_client
    # Point the session factory at a closed port: connection is refused
    # immediately (deterministic, no sleep) so the readiness DB check fails.
    dead_engine = create_async_engine(
        "postgresql+psycopg://nobody:nobody@127.0.0.1:1/none",
        connect_args={"connect_timeout": 2},
    )
    monkeypatch.setattr(
        app.state,
        "sessionmaker",
        async_sessionmaker(dead_engine, expire_on_commit=False),
    )
    try:
        response = await client.get("/readyz")
    finally:
        await dead_engine.dispose()

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not-ready"
    assert body["checks"]["database"] == "down"
