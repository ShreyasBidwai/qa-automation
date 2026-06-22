"""Disposable-DB provisioning — the real-DB execution edge (B10, ADR-0043).

Heavy lane (``db_state``): provisions a throwaway Postgres database from migrations,
asserts table state against it, resets, and drops. Also pins that the provisioner
refuses a prod-named database before creating anything.

Run via ``make test-db-state`` (kept out of the fast suite). Manages its own
databases; does not use the per-test transactional fixtures.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.db_state.errors import ProdTargetRefused
from app.db_state.oracle import TablePredicate, TableStateCheck, evaluate_table_state
from app.db_state.provision import DisposableDatabase

pytestmark = pytest.mark.db_state

# The "target app's migrations", as deterministic SQL — a single orders table.
_MIGRATIONS = [
    "CREATE TABLE orders ("
    "  id integer PRIMARY KEY, status text, total integer, deleted_at timestamptz)",
]


def _check(predicate: TablePredicate, row_id: int) -> TableStateCheck:
    return TableStateCheck("orders", predicate, {"id": row_id})


def _admin_url() -> str:
    """The server's admin DB URL, derived from the configured DATABASE_URL."""
    return (
        make_url(os.environ["DATABASE_URL"])
        .set(database="postgres")
        .render_as_string(hide_password=False)
    )


async def test_provision_assert_reset_drop_against_a_disposable_db() -> None:
    name = f"polaris_dbstate_{uuid.uuid4().hex[:8]}"
    disposable = DisposableDatabase(
        admin_url=_admin_url(), db_name=name, migrations_sql=_MIGRATIONS
    )
    target = await disposable.provision()
    try:
        assert target.disposable  # provisioner only yields gate-approved targets

        engine = create_async_engine(target.url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO orders (id, status, total) "
                        "VALUES (1, 'paid', 500)"
                    )
                )
            async with engine.connect() as conn:
                # The row landed correctly → ROW_PRESENT passes.
                present = await evaluate_table_state(
                    conn, _check(TablePredicate.ROW_PRESENT, 1)
                )
                assert present.passed and present.observed is not None
                assert present.observed["status"] == "paid"
                # A row that did NOT land → the assertion fails (honest).
                missing = await evaluate_table_state(
                    conn, _check(TablePredicate.ROW_PRESENT, 2)
                )
                assert not missing.passed
        finally:
            await engine.dispose()

        # reset() truncates → the disposable DB is clean again between runs.
        await disposable.reset()
        engine = create_async_engine(target.url)
        try:
            async with engine.connect() as conn:
                after = await evaluate_table_state(
                    conn, _check(TablePredicate.ROW_ABSENT, 1)
                )
                assert after.passed  # the row is gone after reset
        finally:
            await engine.dispose()
    finally:
        await disposable.drop()


async def test_provisioner_refuses_a_prod_named_database() -> None:
    disposable = DisposableDatabase(
        admin_url=_admin_url(),
        db_name="orders_production_db",  # name screams prod → must be refused
        migrations_sql=_MIGRATIONS,
    )
    with pytest.raises(ProdTargetRefused):
        await disposable.provision()
    # The gate runs before any CREATE, so nothing to clean up — assert it's absent.
    engine = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = (
                await conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :n"),
                    {"n": "orders_production_db"},
                )
            ).first()
        assert exists is None  # the prod-named DB was never created
    finally:
        await engine.dispose()
