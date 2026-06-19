"""Severity scoring + triage ranking (T7.3).

Fills the Finding ``severity`` placeholder and ranks a run's findings so a
high-blast, high-confidence bug sorts to the top and a low-confidence "behaviour
changed" on an isolated node sinks (ADR-0022).

Severity is scored from two inputs — the **blast radius** of the finding's anchor
node (via an injected ``CrossLayerResolver.impact`` slice: count of dependent
pages/roles/tables) and the **failure shape** (errors/5xx and rule-derived
violations weigh heavier than soft characterization mismatches) — and persisted
into the existing string column (no migration). Ranking is computed on read:
``severity desc, confidence desc, root_cause_key`` (confidence already on the
Finding from T7.2). Everything here is deterministic and project-scoped
(Standards §5, §7).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.cross_layer import CrossLayerError, Impact
from app.models.enums import OracleSource, Outcome, Severity
from app.models.finding import Finding
from app.models.result import Result
from app.repositories.finding_repository import FindingRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.test_case_repository import TestCaseRepository

logger = logging.getLogger("app.reporting")

# A node with this many or more dependents (callers + written tables + gating
# roles) is a "wide" blast (ADR-0022) — a product threshold, fixed by ADR.
WIDE_BLAST_THRESHOLD = 3

# Severity ranks for ordering; ``unset`` (and anything unknown) sinks below all.
_SEVERITY_RANK: dict[str, int] = {
    Severity.CRITICAL.value: 3,
    Severity.MAJOR.value: 2,
    Severity.MINOR.value: 1,
}

# Confidence ranks for ordering — the same oracle tier order as ADR-0021.
_CONFIDENCE_RANK: dict[OracleSource, int] = {
    OracleSource.CHARACTERIZATION: 1,
    OracleSource.RULE_DERIVED: 2,
    OracleSource.SPEC_GROUNDED: 3,
}


class ImpactResolver(Protocol):
    """The slice of CrossLayerResolver the scorer needs (injectable for tests)."""

    async def impact(self, project_id: uuid.UUID, node_id: uuid.UUID) -> Impact: ...


# --- pure scoring + ranking --------------------------------------------------


def blast_radius(impact: Impact) -> int:
    """Count of things depending on the node: callers + written tables + roles."""
    return len(impact.callers) + len(impact.writes) + len(impact.roles)


def score_severity(
    blast: int, outcome: Outcome, oracle_source: OracleSource
) -> Severity:
    """Severity from blast radius × failure shape (ADR-0022 thresholds).

    ``soft`` = a fail with a characterization oracle (behaviour merely changed);
    ``hard``/``rule`` = an error (5xx-class) or a rule/spec violation, which weigh
    heavier. critical iff (hard|rule) and wide; minor iff soft and not wide; else
    major — so a 5xx/error always outranks a soft mismatch at equal blast.
    """
    wide = blast >= WIDE_BLAST_THRESHOLD
    soft = outcome is Outcome.FAIL and oracle_source is OracleSource.CHARACTERIZATION
    if not soft and wide:
        return Severity.CRITICAL
    if soft and not wide:
        return Severity.MINOR
    return Severity.MAJOR


def severity_rank(severity: str) -> int:
    """Ordering rank for a stored severity string; unset/unknown → 0."""
    return _SEVERITY_RANK.get(severity, 0)


def confidence_rank(oracle_source: OracleSource) -> int:
    """Ordering rank for a finding's confidence (oracle tier)."""
    return _CONFIDENCE_RANK[oracle_source]


def rank_key(finding: Finding) -> tuple[int, int, str]:
    """Deterministic triage sort key: severity desc, confidence desc, key asc."""
    return (
        -severity_rank(finding.severity),
        -confidence_rank(finding.oracle_source),
        finding.root_cause_key,
    )


def rank_findings(findings: Sequence[Finding]) -> list[Finding]:
    """Findings in triage order (severity × confidence, stable tie-break)."""
    return sorted(findings, key=rank_key)


# --- scoring + ranking against the store -------------------------------------


class SeverityScorer:
    """Scores findings' severity (via blast radius) and ranks a run's findings."""

    def __init__(
        self, session: AsyncSession, *, impact_resolver: ImpactResolver
    ) -> None:
        self._session = session
        self._findings = FindingRepository(session)
        self._results = ResultRepository(session)
        self._cases = TestCaseRepository(session)
        self._impact = impact_resolver

    async def score(self, project_id: uuid.UUID, finding: Finding) -> Finding:
        """Compute + persist one finding's severity (project-scoped)."""
        result = await self._results.get(project_id, finding.result_id)
        outcome = result.outcome if result is not None else Outcome.FAIL
        blast = await self._blast(project_id, result)
        finding.severity = score_severity(blast, outcome, finding.oracle_source).value
        await self._session.flush()
        return finding

    async def score_run(
        self, project_id: uuid.UUID, run_id: uuid.UUID
    ) -> list[Finding]:
        """Score every finding of a run, then return them in triage order."""
        findings = await self._findings.list_for_run(project_id, run_id)
        for finding in findings:
            await self.score(project_id, finding)
        ranked = rank_findings(findings)
        logger.info(
            "reporting.findings_scored",
            extra={
                "project_id": str(project_id),
                "run_id": str(run_id),
                "findings": len(ranked),
            },
        )
        return ranked

    async def ranked_for_run(
        self, project_id: uuid.UUID, run_id: uuid.UUID
    ) -> list[Finding]:
        """A run's findings in triage order, computed on read (project-scoped)."""
        return rank_findings(await self._findings.list_for_run(project_id, run_id))

    async def _blast(self, project_id: uuid.UUID, result: Result | None) -> int:
        """Blast radius of the finding's anchor (the failing test's target node)."""
        if result is None:
            return 0
        case = await self._cases.get(project_id, result.test_case_id)
        if case is None or case.target_node is None:
            return 0
        try:
            impact = await self._impact.impact(project_id, case.target_node)
        except CrossLayerError:
            # The anchor node is gone from the Brain — no blast, not a failure.
            return 0
        return blast_radius(impact)
