"""FastAPI dependencies for the v1 API (Standards §5 — thin wiring).

A per-request DB session (commit on success, rollback on error) and accessors for
the shared ``app.state`` collaborators (job registry + the injectable ports).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .jobs import JobRegistry
from .ports import Ingestor, RunExecutor


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A request-scoped session from the app sessionmaker (commit/rollback)."""
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_jobs(request: Request) -> JobRegistry:
    jobs: JobRegistry = request.app.state.jobs
    return jobs


def get_run_executor(request: Request) -> RunExecutor:
    executor: RunExecutor | None = getattr(request.app.state, "run_executor", None)
    if executor is None:
        raise HTTPException(status_code=503, detail="run executor not configured")
    return executor


def get_ingestor(request: Request) -> Ingestor:
    ingestor: Ingestor | None = getattr(request.app.state, "ingestor", None)
    if ingestor is None:
        raise HTTPException(status_code=503, detail="ingestor not configured")
    return ingestor
