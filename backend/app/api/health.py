"""Liveness and readiness endpoints (TRD §4, Standards §9).

Routers stay thin: they consult shared state and delegate the DB check to the
service layer.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response

from ..core.state import app_state
from ..services import health_service

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness — the process is up. No dependencies checked."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request, response: Response) -> dict[str, Any]:
    """Readiness — 200 only when startup is complete and the DB is reachable."""
    if not app_state.is_ready:
        response.status_code = 503
        reason = "draining" if app_state.is_draining else "starting"
        return {"status": "not-ready", "reason": reason}

    if not await health_service.check_database_ready(request.app.state.sessionmaker):
        response.status_code = 503
        return {"status": "not-ready", "checks": {"database": "down"}}

    return {"status": "ready", "checks": {"database": "up"}}
