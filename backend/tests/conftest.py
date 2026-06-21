"""Test fixtures (Standards §15).

Spins an isolated, ephemeral test database per pytest worker (parallel-safe),
migrates it with Alembic, and points application settings at it. The app is then
exercised through its real lifespan + an in-process ASGI transport — no network,
no sleeps.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    """Create a fresh test database, migrate it, and expose its URL.

    The database name is namespaced by the xdist worker so parallel workers
    never share state. Settings are repointed at it for the whole session.
    """
    base_url = make_url(os.environ["DATABASE_URL"])
    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    db_name = f"{base_url.database}_test_{worker}"
    admin_url = base_url.set(database="postgres")
    test_url = base_url.set(database=db_name)
    rendered = test_url.render_as_string(hide_password=False)

    def _recreate() -> None:
        engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            with engine.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        finally:
            engine.dispose()

    def _drop() -> None:
        engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            with engine.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        finally:
            engine.dispose()

    _recreate()

    # Repoint settings at the test DB before anything builds an engine.
    os.environ["DATABASE_URL"] = rendered
    get_settings.cache_clear()

    # Apply migrations (pgvector + schema) via Alembic, exactly as production.
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", rendered)
    command.upgrade(cfg, "head")

    try:
        yield rendered
    finally:
        _drop()


@pytest_asyncio.fixture
async def app_client(
    test_database_url: str,
) -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI]]:
    """The real app, started through its lifespan, behind an in-process client."""
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield client, app


@pytest_asyncio.fixture
async def authed_client(
    app_client: tuple[httpx.AsyncClient, FastAPI],
) -> tuple[httpx.AsyncClient, FastAPI]:
    """The app client with a signed-in user's bearer token attached (B2).

    Protected data endpoints now require auth; this signs up a fresh user and sets
    the Authorization header so the existing API tests run authenticated.
    """
    client, app = app_client
    email = f"fixture-{uuid.uuid4().hex[:12]}@example.test"
    resp = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": "fixturepw1"}
    )
    assert resp.status_code == 201, resp.text
    client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    return client, app


@pytest_asyncio.fixture
async def db_session(test_database_url: str) -> AsyncIterator[AsyncSession]:
    """A session wrapped in a transaction that is rolled back after each test."""
    engine = create_async_engine(test_database_url)
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.fixture
def endpoint_spec() -> object:
    """A representative EndpointSpec (mirrors the T1.3 Laravel `users.store`
    fixture) exercising required / email / integer / min / max / exists /
    unique / auth — the input for the generation tests.
    """
    from app.ingestion.models import (
        EndpointSpec,
        FieldConstraints,
        RelationalRule,
        ValidationField,
    )

    return EndpointSpec(
        method="POST",
        uri="api/users",
        route_name="users.store",
        auth_required=True,
        path_params=[],
        query_params=[],
        validation_fields=[
            ValidationField(
                name="name",
                raw_rules=["required", "string", "max:255"],
                required=True,
                type="string",
                constraints=FieldConstraints(max=255.0),
            ),
            ValidationField(
                name="email",
                raw_rules=["required", "email", "unique:users,email"],
                required=True,
                type="email",
                constraints=FieldConstraints(),
                relational=RelationalRule(kind="unique", table="users", column="email"),
            ),
            ValidationField(
                name="age",
                raw_rules=["required", "integer", "min:18", "max:120"],
                required=True,
                type="integer",
                constraints=FieldConstraints(min=18.0, max=120.0),
            ),
            ValidationField(
                name="country_id",
                raw_rules=["required", "exists:countries,id"],
                required=True,
                type="unknown",
                constraints=FieldConstraints(),
                relational=RelationalRule(
                    kind="exists", table="countries", column="id"
                ),
            ),
            ValidationField(
                name="newsletter",
                raw_rules=["boolean"],
                required=False,
                type="boolean",
                constraints=FieldConstraints(),
            ),
        ],
    )
