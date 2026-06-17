"""Minimal FastAPI control-plane placeholder.

This is scaffolding so the Docker Compose stack boots and the health contract
(Engineering Standards §9) is in place. The real API — routers/services/
repositories behind the app-factory pattern — lands in later tasks.
"""

from __future__ import annotations

import os

import psycopg
from fastapi import FastAPI, Response


def _libpq_dsn(url: str) -> str:
    """Normalize a SQLAlchemy-style URL to a libpq DSN psycopg can consume.

    The app config uses ``postgresql+psycopg://…`` (SQLAlchemy dialect); the
    raw psycopg driver wants ``postgresql://…``.
    """
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def create_app() -> FastAPI:
    app = FastAPI(title="QA Automation Platform API", version="0.0.0")

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        """Liveness — the process is up. No dependencies checked."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    def readyz(response: Response) -> dict[str, object]:
        """Readiness — gates traffic; checks the database is reachable."""
        dsn = _libpq_dsn(os.environ.get("DATABASE_URL", ""))
        try:
            with psycopg.connect(dsn, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
        except Exception:
            response.status_code = 503
            return {"status": "not-ready", "checks": {"database": "down"}}
        return {"status": "ready", "checks": {"database": "up"}}

    return app


app = create_app()
