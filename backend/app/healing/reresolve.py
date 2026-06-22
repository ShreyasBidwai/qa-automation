"""Re-resolve a test's moved target against the current Brain (B8, ADR-0040).

When a test fails to *locate* its endpoint, the route most likely moved. We re-bind
it deterministically: the test carries the route's stable identity (its
``route_name``, e.g. ``users.store``) in ``preconditions``; the re-ingested Brain
carries the same identity on its endpoint nodes with the *new* URI. Matching on the
stable name re-derives where the route went — no model required.

Confidence is gated honestly:

  - ``high`` — a single endpoint node shares the test's ``route_name`` and sits at
    a *different* URI. That is an unambiguous rename/move.
  - ``low`` — no name match, but exactly one endpoint node of the same method
    shares the route's last path segment at a different URI. A structural guess; it
    is surfaced, not applied (below the heal threshold).
  - none — no confident re-binding (route deleted, ambiguous, or no code model).
    Reported honestly as an unhealed failure, never guessed.

AI-assisted mapping for the genuinely ambiguous middle is the labelled extension
point (ADR-0040); it is intentionally not wired here so the deterministic spine
stands alone.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import NodeKind
from app.repositories.node_repository import NodeRepository


@dataclass(frozen=True)
class RouteResolution:
    """A re-binding of a moved route, with the basis and confidence behind it."""

    method: str
    old_path: str
    new_path: str
    route_name: str | None
    confidence: str  # "high" | "low"
    basis: str  # "route_name" | "structural"
    rationale: str


def _final_segment(uri: str) -> str:
    parts = [p for p in uri.strip("/").split("/") if p]
    return parts[-1] if parts else ""


async def reresolve_route(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    preconditions: dict[str, Any],
) -> RouteResolution | None:
    """Re-bind the endpoint in ``preconditions`` to its current Brain location.

    Reads the test's baked-in addressing (``preconditions["endpoint"]`` =
    ``{method, uri, route_name}``) and searches the project's endpoint nodes for
    where that route now lives. Returns the highest-confidence re-binding, or
    ``None`` when none can be made honestly.
    """
    endpoint = (preconditions or {}).get("endpoint") or {}
    old_uri = str(endpoint.get("uri") or "").strip()
    method = str(endpoint.get("method") or "").upper()
    route_name = endpoint.get("route_name")
    if not old_uri or not method:
        return None  # nothing to re-bind against

    nodes = await NodeRepository(session).list_by_kind(project_id, NodeKind.ENDPOINT)
    # Candidate endpoints of the same method that sit at a *different* URI than the
    # test currently addresses. A node still at the old URI is, by construction, not
    # a move and is excluded — so a lingering stale node never confounds the match.
    moved = [
        node
        for node in nodes
        if str((node.attributes or {}).get("method") or "").upper() == method
        and str((node.attributes or {}).get("uri") or "").strip()
        and str((node.attributes or {}).get("uri") or "").strip() != old_uri
    ]

    # High confidence: the stable route name re-binds to exactly one new URI.
    if route_name:
        by_name = [
            node for node in moved if (node.attributes or {}).get("name") == route_name
        ]
        if len(by_name) == 1:
            new_uri = str(by_name[0].attributes["uri"]).strip()
            return RouteResolution(
                method=method,
                old_path=old_uri,
                new_path=new_uri,
                route_name=route_name,
                confidence="high",
                basis="route_name",
                rationale=(
                    f"route '{route_name}' moved from "
                    f"{method} /{old_uri.lstrip('/')} to "
                    f"{method} /{new_uri.lstrip('/')}"
                ),
            )
        if len(by_name) > 1:
            return None  # the name maps to several URIs — ambiguous, do not guess

    # Low confidence: no name match, but one same-method endpoint shares the last
    # path segment. A plausible structural guess — surfaced, below the heal bar.
    segment = _final_segment(old_uri)
    by_segment = [
        node
        for node in moved
        if segment and _final_segment(str(node.attributes["uri"])) == segment
    ]
    if len(by_segment) == 1:
        new_uri = str(by_segment[0].attributes["uri"]).strip()
        return RouteResolution(
            method=method,
            old_path=old_uri,
            new_path=new_uri,
            route_name=route_name,
            confidence="low",
            basis="structural",
            rationale=(
                f"no route-name match; one {method} endpoint shares the "
                f"'/{segment}' segment at /{new_uri.lstrip('/')} — structural guess"
            ),
        )
    return None
