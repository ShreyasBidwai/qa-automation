"""Application factory (Standards §5).

Wiring only — middleware, error handlers, routers. Runtime config and lifecycle
live in ``app.core``; the server entrypoint is ``app.__main__``.
"""

from __future__ import annotations

from fastapi import FastAPI

from .api.health import router as health_router
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

    # Liveness/readiness are unversioned, top-level endpoints (TRD §4).
    app.include_router(health_router)
    # Versioned API (`/api/v1`) routers attach in later tasks.

    return app
