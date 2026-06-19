"""FindingAssembler — turn a run's Results into Findings (T7.1).

The model + assembly half of Sprint 7 reporting: one Finding per failing (or
erroring) result for now — grouping is T7.2. For each non-passing result it reads
the failing test case (its oracle_source = the finding's confidence, its
``expected`` oracle, and its layer) and resolves the cross-layer location
(page→endpoint→table) from the test case's target node via an injected resolver,
then persists a project-scoped Finding referencing the run + result. Passing
results produce nothing. Deterministic; reads only (never alters Results).
Repositories do the project-scoped reads/writes (Standards §5).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.cross_layer import CrossLayerError, Subgraph
from app.models.enums import FindingLayer, NodeKind, Outcome, TestLayer
from app.models.finding import SEVERITY_UNSET, STATUS_OPEN, Finding
from app.models.result import Result
from app.models.test_case import TestCase
from app.repositories.finding_repository import FindingRepository
from app.repositories.test_case_repository import TestCaseRepository

from .errors import FindingAssemblyError

logger = logging.getLogger("app.reporting")

# A finding is located on the stack from how its case ran. ``db`` findings come
# from DB-level oracles (later work), so no case layer maps to it yet.
_LAYER_MAP: dict[TestLayer, FindingLayer] = {
    TestLayer.UI: FindingLayer.UI,
    TestLayer.API: FindingLayer.API,
    TestLayer.INTEGRATION: FindingLayer.API,
}


class LocationResolver(Protocol):
    """The slice of CrossLayerResolver the assembler needs (injectable for tests)."""

    async def journey(
        self, project_id: uuid.UUID, node_id: uuid.UUID, max_depth: int = 3
    ) -> Subgraph: ...


def _location_payload(subgraph: Subgraph | None) -> dict[str, Any]:
    if subgraph is None:
        return {}
    nodes = subgraph.nodes
    return {
        "page": next((n.name for n in nodes if n.kind is NodeKind.PAGE), None),
        "endpoints": [n.name for n in nodes if n.kind is NodeKind.ENDPOINT],
        "tables": [n.name for n in nodes if n.kind is NodeKind.TABLE],
    }


def _title(layer: FindingLayer, location: dict[str, Any]) -> str:
    endpoints = location.get("endpoints") or []
    target = location.get("page") or (endpoints[0] if endpoints else "unknown target")
    return f"{layer.value} failure at {target}"


class FindingAssembler:
    def __init__(self, session: AsyncSession, *, resolver: LocationResolver) -> None:
        self._cases = TestCaseRepository(session)
        self._repo = FindingRepository(session)
        self._resolver = resolver

    async def assemble(
        self, *, project_id: uuid.UUID, results: Sequence[Result]
    ) -> list[Finding]:
        """Build + persist one Finding per non-passing result (project-scoped)."""
        findings: list[Finding] = []
        for result in results:
            if result.outcome is Outcome.PASS:
                continue  # passing results are not findings
            case = await self._cases.get(project_id, result.test_case_id)
            if case is None:
                raise FindingAssemblyError(
                    f"result {result.id} references test case "
                    f"{result.test_case_id} not in project {project_id}"
                )
            location = _location_payload(await self._resolve(project_id, case))
            layer = _LAYER_MAP[case.layer]
            finding = await self._repo.add(
                Finding(
                    project_id=project_id,
                    run_id=result.run_id,
                    result_id=result.id,
                    title=_title(layer, location),
                    layer=layer,
                    oracle_source=case.oracle_source,
                    expected=dict(case.expected),
                    evidence_ref=result.evidence_ref,
                    location=location,
                    severity=SEVERITY_UNSET,
                    status=STATUS_OPEN,
                )
            )
            findings.append(finding)

        logger.info(
            "reporting.findings_assembled",
            extra={"project_id": str(project_id), "findings": len(findings)},
        )
        return findings

    async def _resolve(self, project_id: uuid.UUID, case: TestCase) -> Subgraph | None:
        """Cross-layer location for the case's target node, or None if unresolved."""
        if case.target_node is None:
            return None
        try:
            return await self._resolver.journey(project_id, case.target_node)
        except CrossLayerError:
            # The target node is gone from the Brain — no location, not a failure.
            return None
