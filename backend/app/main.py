"""Application factory (Standards §5).

Wiring only — middleware, error handlers, routers. Runtime config and lifecycle
live in ``app.core``; the server entrypoint is ``app.__main__``.
"""

from __future__ import annotations

from fastapi import FastAPI

from .api.auth import router as auth_router
from .api.documents import router as documents_router
from .api.findings import router as findings_router
from .api.heals import router as heals_router
from .api.health import router as health_router
from .api.incidents import router as incidents_router
from .api.ops import router as ops_router
from .api.orgs import router as orgs_router
from .api.projects import router as projects_router
from .api.runs import router as runs_router
from .core.config import get_settings
from .core.errors import register_exception_handlers
from .core.lifespan import lifespan
from .core.rate_limit import build_rate_limiter
from .middleware.request_id import RequestIdMiddleware
from .services.mailer import build_mailer


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="QA Automation Platform API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(RequestIdMiddleware, header_name=settings.request_id_header)
    register_exception_handlers(app)

    # Jobs are a durable Postgres queue now (B4, ADR-0034) — no app.state registry.
    # The executor + ingestor ports are set by composition (or a test); absent →
    # routes 503.
    app.state.run_executor = None
    app.state.ingestor = None
    # Embedding provider (B9): composed in app.__main__ (local fastembed); a test
    # sets the deterministic stub. None → document ingest routes 503.
    app.state.embedding_provider = None
    # Transactional mailer (B2): the dev stub logs the reset link; a test overrides
    # this to capture it. Real SMTP is composed in later (no creds needed to boot).
    app.state.mailer = build_mailer()
    # Per-IP rate limiter for the sensitive auth endpoints (B11, ADR-0046) —
    # in-memory, single-instance. A test may override it with a clock-controlled one.
    app.state.rate_limiter = build_rate_limiter(settings)

    # Liveness/readiness are unversioned, top-level endpoints (TRD §4).
    app.include_router(health_router)
    # Versioned API (`/api/v1`): auth, orgs/teams, project config, ingest, runs,
    # findings.
    app.include_router(auth_router)
    app.include_router(orgs_router)
    app.include_router(projects_router)
    app.include_router(runs_router)
    app.include_router(findings_router)
    app.include_router(ops_router)
    app.include_router(documents_router)
    app.include_router(incidents_router)
    app.include_router(heals_router)

    return app
