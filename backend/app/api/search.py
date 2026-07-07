"""Global name search — the ⌘K command palette (ADR-0068).

``GET /api/v1/search`` jumps to a Project / Finding / Run by name. Deterministic,
indexed ``ILIKE`` (pg_trgm-backed) — NOT semantic/embeddings search, so it never
touches the AI or embedding layer. Org-scoped exactly like the open-findings inbox
and the account dashboard: only the caller's viewable orgs' rows are ever
considered (ADR-0033) — a project/finding/run in an org the caller doesn't belong to
is simply absent from the results, never a 403 (existence isn't leaked either way).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.reporting.search import ALLOWED_TYPES, SearchReader
from app.repositories.organization_repository import OrganizationRepository

from .deps import CurrentUser, get_session
from .schemas import SearchResponse, SearchResultItem

router = APIRouter(prefix="/api/v1", tags=["search"])


def _parse_types(raw: str | None) -> tuple[str, ...]:
    """Validate the client-chosen ``types`` filter against the allow-list
    (CLAUDE.md: never feed a client-chosen value straight into a query). Omitted or
    blank ⇒ every type; an unknown value is a 422, not a silently-ignored filter."""
    if raw is None or not raw.strip():
        return ALLOWED_TYPES
    requested = tuple(part.strip() for part in raw.split(",") if part.strip())
    unknown = sorted(set(requested) - set(ALLOWED_TYPES))
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"unknown search type(s): {', '.join(unknown)}",
        )
    return requested or ALLOWED_TYPES


@router.get("/search", response_model=SearchResponse)
async def search(
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str, Query(max_length=100)] = "",
    types: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> SearchResponse:
    """Name search across the caller's viewable orgs. ``limit`` applies PER
    requested type (so ``types`` omitted + the default limit returns at most 15 rows
    total — bounded regardless of account size). A blank ``q`` returns no rows rather
    than an unbounded listing."""
    parsed_types = _parse_types(types)
    org_ids = await OrganizationRepository(session).member_org_ids(current_user.id)
    results = await SearchReader(session).search(
        q, types=parsed_types, limit=limit, org_ids=org_ids
    )
    return SearchResponse(
        query=q.strip(),
        items=[
            SearchResultItem(
                type=r.type,
                id=r.id,
                label=r.label,
                subtitle=r.subtitle,
                url=r.url,
            )
            for r in results
        ],
    )
