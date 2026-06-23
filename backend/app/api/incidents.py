"""Internal incidents — operator-only READ surface (dev-suite slice 1, ADR-0047).

``GET /incidents`` (newest-first, filter by phase/project) + ``GET /incidents/{id}``
(with traceback). Cross-tenant, gated by the instance operator flag (``OperatorUser``
→ 403 for a non-operator), NOT org RBAC — exactly like the ops status view. No
mutation: this is the seam the operator UI will consume later. Polaris never
auto-modifies itself in response to an incident (the honesty guardrail).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident
from app.repositories.incident_repository import IncidentRepository

from .deps import OperatorUser, get_session
from .schemas import (
    IncidentDetailResponse,
    IncidentListItem,
    IncidentListResponse,
)

router = APIRouter(prefix="/api/v1", tags=["operator"])


def _list_item(incident: Incident) -> IncidentListItem:
    return IncidentListItem(
        id=incident.id,
        created_at=incident.created_at,
        phase=incident.phase,
        component=incident.component,
        project_id=incident.project_id,
        run_id=incident.run_id,
        exception_type=incident.exception_type,
        message=incident.message,
        fingerprint=incident.fingerprint,
    )


@router.get("/incidents", response_model=IncidentListResponse)
async def list_incidents(
    operator: OperatorUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    phase: Annotated[str | None, Query()] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> IncidentListResponse:
    """Captured internal failures, newest-first (operator-only; 403 otherwise)."""
    repo = IncidentRepository(session)
    incidents = await repo.list(
        phase=phase, project_id=project_id, limit=limit, offset=offset
    )
    total = await repo.count(phase=phase, project_id=project_id)
    return IncidentListResponse(
        items=[_list_item(incident) for incident in incidents],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/incidents/{incident_id}", response_model=IncidentDetailResponse)
async def get_incident(
    incident_id: uuid.UUID,
    operator: OperatorUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IncidentDetailResponse:
    """One incident with its traceback (operator-only; 403 otherwise, 404 if absent)."""
    incident = await IncidentRepository(session).get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return IncidentDetailResponse(
        **_list_item(incident).model_dump(), traceback=incident.traceback
    )
