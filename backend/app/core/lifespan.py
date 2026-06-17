"""Graceful startup and shutdown (Standards §11).

Startup:  validate config (done at settings load) → create engine → connect with
          bounded retries → verify migration state → flip readiness on.
Shutdown: flip readiness off (stop new traffic) → dispose the engine. In-flight
          request draining is owned by the server's graceful-shutdown timeout;
          the server's signal handler flips readiness off the moment SIGTERM
          arrives, before the drain begins (see ``app.__main__``).
"""

from __future__ import annotations

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

    app_state.is_ready = True
    logger.info("startup: ready")

    try:
        yield
    finally:
        app_state.is_ready = False
        app_state.is_draining = True
        logger.info("shutdown: readiness disabled, releasing resources")
        await engine.dispose()
        logger.info("shutdown: database connections closed")
