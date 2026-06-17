"""Health/readiness logic (Standards §5 — services own logic, §9 readiness)."""

from __future__ import annotations

import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..repositories import health_repository

logger = logging.getLogger("app.health")


async def check_database_ready(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> bool:
    """Return whether the database answers a trivial query.

    Failures are logged by type only — never with the DSN (Standards §8).
    """
    try:
        async with sessionmaker() as session:
            await health_repository.ping(session)
        return True
    except (SQLAlchemyError, OSError) as exc:
        logger.warning(
            "readiness database check failed",
            extra={"error_type": type(exc).__name__},
        )
        return False
