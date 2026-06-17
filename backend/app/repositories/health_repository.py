"""Data-access for health checks (Standards §5 — repositories own DB access)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def ping(session: AsyncSession) -> None:
    """Execute a trivial query; raises if the database is not reachable."""
    await session.execute(text("SELECT 1"))
