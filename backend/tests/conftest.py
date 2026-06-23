"""Test fixtures (Standards §15).

Spins an isolated, ephemeral test database per pytest worker (parallel-safe),
migrates it with Alembic, and points application settings at it. The app is then
exercised through its real lifespan + an in-process ASGI transport — no network,
no sleeps.

**Per-test transactional isolation (ADR-0042).** The suite runs single-process on
one shared database, so anything a test commits would otherwise persist into the
next test's reads. Every test instead runs inside ONE outer transaction on ONE
connection, rolled back at teardown. The ``app_client`` (what the API commits) and
``db_session`` (direct DB access) fixtures bind to the SAME connection-bound
sessionmaker, so a row the API commits and a row a test inserts directly live in the
same transaction and vanish together — committed rows can never leak between tests,
regardless of run order.
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
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session as SyncSession
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.organization import Organization
from app.models.project import Project


@event.listens_for(SyncSession, "before_flush")
def _auto_org_for_bare_test_projects(
    session: SyncSession, flush_context: object, instances: object
) -> None:
    """Give every factory-made project an org (B3, ADR-0032 makes ``org_id`` NOT
    NULL).

    Test-only: the legacy unit tests build bare ``Project`` rows via
    ``tests.factories`` with no org. Rather than thread an org through ~90 call
    sites, any pending project without an ``org_id`` gets a fresh throwaway org
    here. Production is unaffected (this module is only imported under pytest); a
    client-side UUID avoids needing a nested flush to resolve the FK.
    """
    for obj in list(session.new):
        if isinstance(obj, Project) and obj.org_id is None:
            org = Organization(id=uuid.uuid4(), name="test-org", is_personal=False)
            session.add(org)
            obj.org_id = org.id


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
    # Tiny pools for the per-test app engine (one created per app_client test): the
    # production defaults (10 + 5 overflow) would let a single shuffled run's many
    # short-lived app engines spike past the server connection cap. Tests are
    # single-process and use one connection at a time, so 1 is ample.
    os.environ["DB_POOL_SIZE"] = "1"
    os.environ["DB_POOL_MAX_OVERFLOW"] = "0"
    # Generous auth rate limits for the DEFAULT test app so ordinary multi-request
    # tests never trip the limiter (B11); the rate-limit tests override
    # ``app.state.rate_limiter`` with small, clock-controlled limits explicitly.
    os.environ["AUTH_SIGNIN_RATE_LIMIT"] = "100000"
    os.environ["AUTH_SIGNUP_RATE_LIMIT"] = "100000"
    os.environ["AUTH_PASSWORD_RESET_RATE_LIMIT"] = "100000"
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
async def _isolation(
    test_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """One connection + outer transaction shared by the app and direct DB access.

    The bound sessionmaker uses ``join_transaction_mode="create_savepoint"``: a
    session that ``commit()``s on a connection already inside a transaction releases
    a SAVEPOINT instead of committing for real. So every commit the code under test
    makes (an API request, a seeding block) lands inside the one outer transaction,
    and rolling it back at teardown discards everything — committed rows can't leak
    to the next test, whatever the run order. ``app_client`` and ``db_session`` both
    bind to THIS sessionmaker, so the API's commits and a test's direct inserts share
    the transaction and roll back together (the share is the whole point — without
    it, the rollback wouldn't cover what the API committed). The job worker is
    disabled in tests, so nothing captured the app's original sessionmaker before the
    swap, and dispatched jobs run as background tasks after the request session
    closes — the single connection is only ever touched serially.
    """
    # NullPool: the per-test engine holds no idle connections, so a heavy
    # (shuffled) run can't accumulate connections toward the server cap — each test
    # opens exactly one connection and frees it at teardown.
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    connection = await engine.connect()
    outer = await connection.begin()
    sessionmaker = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield sessionmaker
    finally:
        if outer.is_active:
            await outer.rollback()
        await connection.close()
        await engine.dispose()


@pytest_asyncio.fixture
async def app_client(
    _isolation: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI]]:
    """The real app behind an in-process client, bound to the shared transaction.

    The app boots through its real lifespan; we then repoint
    ``app.state.sessionmaker`` at the same connection-bound sessionmaker
    ``db_session`` uses. Every request-time DB read goes through
    ``request.app.state.sessionmaker`` (deps/runs/projects/health), so the swap
    captures everything the API commits into the per-test transaction.
    """
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with LifespanManager(app):
        # Share the per-test transaction: all request-time DB work now runs on the
        # one connection that is rolled back at teardown (see _isolation).
        app.state.sessionmaker = _isolation
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
async def db_session(
    _isolation: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """A direct DB session inside the shared per-test transaction (rolled back).

    Bound to the same connection as ``app_client``, so direct inserts and anything
    the API commits share one transaction and are discarded together at teardown.
    """
    async with _isolation() as session:
        yield session


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
