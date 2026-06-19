"""FindingAssembler — turn a run's Results into root-cause-grouped Findings.

T7.1 emitted one Finding per failing result; T7.2 groups failures that share a
**root cause** into a single Finding that "explains N tests" and dedupes identical
duplicate failures within the run (ADR-0021).

For each non-passing result it resolves the cross-layer location
(page→endpoint→table) from the failing case's target node via an injected
resolver and computes a deterministic ``root_cause_key`` = deepest shared failing
node + failure signature. Results sharing a key collapse into one Finding;
within a group the same test (``test_case_id``) is counted once. The Finding's
confidence is the **strongest** ``oracle_source`` in its group, and a group whose
members disagree on oracle tier is flagged ``confidence_mixed``. The retained
``result_id`` is the deterministic-first member; the full membership is written to
``finding_results``. Passing results produce nothing. Deterministic and
project-scoped; reads only (never alters Results); Standards §5, §7.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.cross_layer import CrossLayerError, Subgraph
from app.models.enums import FindingLayer, NodeKind, OracleSource, Outcome, TestLayer
from app.models.finding import SEVERITY_UNSET, STATUS_OPEN, Finding
from app.models.finding_result import FindingResult
from app.models.result import Result
from app.models.test_case import TestCase
from app.repositories.finding_repository import FindingRepository
from app.repositories.finding_result_repository import FindingResultRepository
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

# Oracle-honesty confidence order (ADR-0021): spec-grounded is gold, rule-derived
# is strong, characterization only pins current behaviour. The strongest member
# sets the group's confidence; one strong member lifts the whole group.
_ORACLE_STRENGTH: dict[OracleSource, int] = {
    OracleSource.CHARACTERIZATION: 1,
    OracleSource.RULE_DERIVED: 2,
    OracleSource.SPEC_GROUNDED: 3,
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


def _anchor(location: Mapping[str, Any]) -> str:
    """The deepest shared failing node: table → endpoint → page (ADR-0021)."""
    for layer in ("tables", "endpoints"):
        names = location.get(layer)
        if names:
            joined = ",".join(sorted(str(n) for n in names))
            return f"{layer[:-1]}={joined}"  # tables→table, endpoints→endpoint
    page = location.get("page")
    if page:
        return f"page={page}"
    return "unlocated"


def _failure_signature(outcome: Outcome, expected: Mapping[str, Any]) -> str:
    """The failure shape: outcome + expected status + assertion kinds (ADR-0021)."""
    parts = [outcome.value]
    status = expected.get("status")
    if status is not None:
        parts.append(f"status={status}")
    assertions = expected.get("assertions")
    if isinstance(assertions, list):
        kinds = sorted(
            str(a.get("kind"))
            for a in assertions
            if isinstance(a, Mapping) and a.get("kind") is not None
        )
        if kinds:
            parts.append("assert=" + ",".join(kinds))
    return "|".join(parts)


def root_cause_key(
    location: Mapping[str, Any], outcome: Outcome, expected: Mapping[str, Any]
) -> str:
    """Deterministic identity of a failure's root cause (ADR-0021).

    ``<deepest shared node> # <failure signature>``. Two failures with the same
    key are the same bug; pure and stable, so re-assembly is idempotent.
    """
    return f"{_anchor(location)}#{_failure_signature(outcome, expected)}"


def strongest_oracle(sources: Iterable[OracleSource]) -> OracleSource:
    """The most trustworthy oracle tier in a group (spec > rule > characterization)."""
    return max(sources, key=lambda s: _ORACLE_STRENGTH[s])


def _title(layer: FindingLayer, location: Mapping[str, Any], explains: int) -> str:
    endpoints = location.get("endpoints") or []
    target = location.get("page") or (endpoints[0] if endpoints else "unknown target")
    suffix = f" (explains {explains} tests)" if explains > 1 else ""
    return f"{layer.value} failure at {target}{suffix}"


@dataclass(frozen=True)
class _Prepared:
    """A failing result resolved to everything grouping needs."""

    result: Result
    case: TestCase
    location: dict[str, Any]
    key: str


def _sort_key(result: Result) -> str:
    # Stable, insertion-independent order: the primary key (always loaded after
    # flush via RETURNING). Determines the deterministic-first representative.
    return str(result.id)


class FindingAssembler:
    def __init__(self, session: AsyncSession, *, resolver: LocationResolver) -> None:
        self._cases = TestCaseRepository(session)
        self._findings = FindingRepository(session)
        self._members = FindingResultRepository(session)
        self._resolver = resolver

    async def assemble(
        self, *, project_id: uuid.UUID, results: Sequence[Result]
    ) -> list[Finding]:
        """Group a run's non-passing results into root-cause Findings (scoped)."""
        prepared = await self._prepare(project_id, results)

        # Group by root cause; dict preserves first-seen order, and we feed it in
        # deterministic result order so grouping is reproducible.
        groups: dict[str, list[_Prepared]] = {}
        for item in sorted(prepared, key=lambda p: _sort_key(p.result)):
            groups.setdefault(item.key, []).append(item)

        findings: list[Finding] = []
        for key in sorted(groups):
            findings.append(await self._build(project_id, key, groups[key]))

        logger.info(
            "reporting.findings_assembled",
            extra={
                "project_id": str(project_id),
                "findings": len(findings),
                "results": len(prepared),
            },
        )
        return findings

    async def _prepare(
        self, project_id: uuid.UUID, results: Sequence[Result]
    ) -> list[_Prepared]:
        prepared: list[_Prepared] = []
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
            key = root_cause_key(location, result.outcome, case.expected)
            prepared.append(_Prepared(result, case, location, key))
        return prepared

    async def _build(
        self, project_id: uuid.UUID, key: str, group: list[_Prepared]
    ) -> Finding:
        """One Finding for a root-cause group: dedupe, confidence, membership."""
        # Dedupe identical duplicate failures: the same test counts once. ``group``
        # is already in deterministic order, so the first kept is deterministic.
        members: list[_Prepared] = []
        seen_cases: set[uuid.UUID] = set()
        for item in group:
            if item.result.test_case_id in seen_cases:
                continue
            seen_cases.add(item.result.test_case_id)
            members.append(item)

        representative = members[0]
        layer = _LAYER_MAP[representative.case.layer]
        oracle_tiers = {m.case.oracle_source for m in members}

        finding = await self._findings.add(
            Finding(
                project_id=project_id,
                run_id=representative.result.run_id,
                result_id=representative.result.id,
                root_cause_key=key,
                explains_count=len(members),
                title=_title(layer, representative.location, len(members)),
                layer=layer,
                oracle_source=strongest_oracle(oracle_tiers),
                confidence_mixed=len(oracle_tiers) > 1,
                expected=dict(representative.case.expected),
                evidence_ref=representative.result.evidence_ref,
                location=representative.location,
                severity=SEVERITY_UNSET,
                status=STATUS_OPEN,
            )
        )
        for member in members:
            await self._members.add(
                FindingResult(
                    project_id=project_id,
                    finding_id=finding.id,
                    result_id=member.result.id,
                )
            )
        return finding

    async def _resolve(self, project_id: uuid.UUID, case: TestCase) -> Subgraph | None:
        """Cross-layer location for the case's target node, or None if unresolved."""
        if case.target_node is None:
            return None
        try:
            return await self._resolver.journey(project_id, case.target_node)
        except CrossLayerError:
            # The target node is gone from the Brain — no location, not a failure.
            return None
