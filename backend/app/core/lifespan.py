"""Graceful startup and shutdown (Standards §11).

Startup:  validate config (done at settings load) → create engine → connect with
          bounded retries → verify migration state → flip readiness on.
Shutdown: flip readiness off (stop new traffic) → dispose the engine. In-flight
          request draining is owned by the server's graceful-shutdown timeout;
          the server's signal handler flips readiness off the moment SIGTERM
          arrives, before the drain begins (see ``app.__main__``).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .db import (
    connect_with_retries,
    create_engine,
    create_sessionmaker,
    verify_migrations,
)
from .state import app_state

logger = logging.getLogger("app.lifespan")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()  # already validated; fail-fast happened on load
    logger.info("startup: initializing", extra={"app_env": settings.app_env})

    engine = create_engine(settings)
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)

    await connect_with_retries(engine, settings)
    logger.info("startup: database reachable")

    current, head = await verify_migrations(engine, settings)
    if head is not None and current == head:
        logger.info("startup: migrations verified", extra={"revision": current})
    else:
        logger.warning(
            "startup: database not at head revision; run migrations",
            extra={"current": current, "head": head},
        )

    # Durable job worker poller (B4, ADR-0034) — drains the queue + recovers
    # orphans/retries after a restart. Gated: the packaged app enables it; the fast
    # lane drives jobs via the dispatch hint and tests the worker directly.
    worker_task: asyncio.Task[None] | None = None
    stop_event: asyncio.Event | None = None
    if settings.job_worker_enabled:
        from app.api.jobs import make_handlers
        from app.services.job_worker import JobWorker

        handlers = make_handlers(
            ingestor=getattr(app.state, "ingestor", None),
            executor=getattr(app.state, "run_executor", None),
        )
        worker = JobWorker(
            app.state.sessionmaker,
            handlers,
            worker_id="poller",
            backoff_base_seconds=settings.job_backoff_base_seconds,
        )
        stop_event = asyncio.Event()
        worker_task = asyncio.create_task(
            worker.run_forever(
                poll_interval_seconds=settings.job_poll_interval_seconds,
                stop_event=stop_event,
            )
        )
        logger.info("startup: job worker poller started")

    app_state.is_ready = True
    logger.info("startup: ready")

    try:
        yield
    finally:
        app_state.is_ready = False
        app_state.is_draining = True
        logger.info("shutdown: readiness disabled, releasing resources")
        if stop_event is not None:
            stop_event.set()
        if worker_task is not None:
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task
        await engine.dispose()
        logger.info("shutdown: database connections closed")
