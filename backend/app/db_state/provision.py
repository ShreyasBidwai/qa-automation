"""Disposable database provisioning (B10, ADR-0043) — the execution edge.

Provision a FRESH disposable Postgres database from a schema source (the target
app's migrations), reset between runs, drop when done. Deterministic, and
gate-enforced: ``provision`` constructs the target ``disposable=True`` and runs it
through ``ensure_disposable`` before handing it back, so this class can only ever
yield a gate-approved, non-prod database — never the app's real/staging data.

CREATE/DROP DATABASE cannot run inside a transaction, so admin DDL uses an
AUTOCOMMIT connection to the server's admin database (mirrors the test harness).
This is the real-DB execution edge → exercised in the ``db_state`` heavy lane.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from .gate import DisposableTarget, ensure_disposable


def _swap_database(url: str, db_name: str) -> str:
    return make_url(url).set(database=db_name).render_as_string(hide_password=False)


class DisposableDatabase:
    """A throwaway Postgres DB built from migrations; reset/drop between runs."""

    def __init__(
        self, *, admin_url: str, db_name: str, migrations_sql: Sequence[str]
    ) -> None:
        self._admin_url = admin_url
        self._db_name = db_name
        self._migrations_sql = list(migrations_sql)
        self._target_url = _swap_database(admin_url, db_name)

    @property
    def target_url(self) -> str:
        return self._target_url

    def _drop_sql(self) -> str:
        return f'DROP DATABASE IF EXISTS "{self._db_name}" WITH (FORCE)'

    async def provision(self) -> DisposableTarget:
        """Gate first, then drop-if-exists, create fresh, apply the migrations.

        The safety gate runs BEFORE any DDL, so a prod/staging-looking name is
        refused without ever creating (or touching) that database.
        """
        target = DisposableTarget(
            url=self._target_url, disposable=True, label=self._db_name
        )
        ensure_disposable(target)  # the load-bearing gate — before anything exists

        await self._admin_exec(self._drop_sql())
        await self._admin_exec(f'CREATE DATABASE "{self._db_name}"')

        engine = create_async_engine(self._target_url)
        try:
            async with engine.begin() as conn:
                for statement in self._migrations_sql:
                    await conn.execute(text(statement))
        finally:
            await engine.dispose()
        return target

    async def reset(self) -> None:
        """Truncate every public table — a deterministic reset between runs."""
        engine = create_async_engine(self._target_url)
        try:
            async with engine.begin() as conn:
                tables = (
                    (
                        await conn.execute(
                            text(
                                "SELECT tablename FROM pg_tables "
                                "WHERE schemaname = 'public'"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for table in tables:
                    await conn.execute(
                        text(f'TRUNCATE TABLE "{table}" RESTART IDENTITY CASCADE')
                    )
        finally:
            await engine.dispose()

    async def drop(self) -> None:
        await self._admin_exec(self._drop_sql())

    async def _admin_exec(self, statement: str) -> None:
        engine = create_async_engine(self._admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                await conn.execute(text(statement))
        finally:
            await engine.dispose()
