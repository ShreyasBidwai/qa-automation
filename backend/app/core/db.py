"""Database engine, session factory, and startup helpers (TRD §3, Standards §11–14).

Uses async SQLAlchemy 2.x over psycopg 3. Connection establishment is bounded
and retried with exponential backoff + jitter; migration state is verified (not
applied) at startup. DB errors are logged by type only — never with the DSN or a
traceback that could embed credentials (Standards §8).
"""

from __future__ import annotations

import asyncio
import logging
import random

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import Settings

logger = logging.getLogger("app.db")


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_max_overflow,
        pool_pre_ping=True,
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def connect_with_retries(engine: AsyncEngine, settings: Settings) -> None:
    """Try to reach the DB, retrying with bounded exponential backoff + jitter.

    Raises ``RuntimeError`` once the attempt budget is exhausted (fail fast).
    """
    last_error_type: str | None = None
    for attempt in range(1, settings.db_connect_max_retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except (SQLAlchemyError, OSError) as exc:
            last_error_type = type(exc).__name__
            if attempt >= settings.db_connect_max_retries:
                break
            delay = min(
                settings.db_connect_base_delay_seconds * 2 ** (attempt - 1),
                settings.db_connect_max_delay_seconds,
            )
            delay += random.uniform(0, settings.db_connect_base_delay_seconds)
            logger.warning(
                "database not reachable yet; retrying",
                extra={
                    "attempt": attempt,
                    "max_attempts": settings.db_connect_max_retries,
                    "error_type": last_error_type,
                    "delay_seconds": round(delay, 2),
                },
            )
            await asyncio.sleep(delay)

    raise RuntimeError(
        f"database unreachable after {settings.db_connect_max_retries} attempts "
        f"(last error: {last_error_type})"
    )


def _alembic_config(settings: Settings) -> Config:
    config = Config()
    config.set_main_option("script_location", "migrations")
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


async def verify_migrations(
    engine: AsyncEngine, settings: Settings
) -> tuple[str | None, str | None]:
    """Return (current_revision, head_revision) without applying anything."""

    def _current_revision(sync_conn: Connection) -> str | None:
        return MigrationContext.configure(sync_conn).get_current_revision()

    async with engine.connect() as conn:
        current = await conn.run_sync(_current_revision)

    head = ScriptDirectory.from_config(_alembic_config(settings)).get_current_head()
    return current, head
