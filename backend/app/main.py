"""Application factory (Standards §5).

Wiring only — middleware, error handlers, routers. Runtime config and lifecycle
live in ``app.core``; the server entrypoint is ``app.__main__``.
"""

from __future__ import annotations

from fastapi import FastAPI

from .api.findings import router as findings_router
from .api.health import router as health_router
from .api.jobs import JobRegistry
from .api.projects import router as projects_router
from .api.runs import router as runs_router
from .core.config import get_settings
from .core.errors import register_exception_handlers
from .core.lifespan import lifespan
from .middleware.request_id import RequestIdMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="QA Automation Platform API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(RequestIdMiddleware, header_name=settings.request_id_header)
    register_exception_handlers(app)

    # Shared API state: the in-process job registry (ADR-0026). The executor +
    # ingestor ports are set by composition (or a test); absent → routes 503.
    app.state.jobs = JobRegistry()
    app.state.run_executor = None
    app.state.ingestor = None

    # Liveness/readiness are unversioned, top-level endpoints (TRD §4).
    app.include_router(health_router)
    # Versioned API (`/api/v1`): project config, ingest, runs, findings.
    app.include_router(projects_router)
    app.include_router(runs_router)
    app.include_router(findings_router)

    return app
