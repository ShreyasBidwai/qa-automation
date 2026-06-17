"""RunReport — the ~10-line, oracle-honest summary of one run (PRD §10).

Deterministic and pure: counts by test type, pass/fail/error outcomes, and the
mandatory oracle-honesty breakdown (rule-derived = strong, characterization =
weak/needs-specs, spec-grounded = 0 this sprint). The gaps section always carries
the honest note that the happy-path oracle is characterization-only until
requirements are ingested. ``persist_coverage`` writes the matching coverage row.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.generator import GeneratedCase
from app.ingestion.models import EndpointSpec
from app.models.coverage import Coverage
from app.models.enums import CoverageDimension, OracleSource, Outcome, TestType
from app.models.result import Result
from app.models.run import Run
from app.repositories.coverage_repository import CoverageRepository

_CHARACTERIZATION_NOTE = (
    "Happy-path oracle is characterization-only (asserts shape, not values) "
    "until requirements are ingested."
)


@dataclass(frozen=True)
class OracleBreakdown:
    rule_derived: int
    characterization: int
    spec_grounded: int


@dataclass(frozen=True)
class RunReport:
    endpoint: str
    route_name: str | None
    run_id: uuid.UUID
    status: str
    total: int
    by_type: dict[str, int]
    outcomes: dict[str, int]
    oracle: OracleBreakdown
    gaps: list[str]

    def _gap_lines(self) -> list[str]:
        lines = [f"  - {gap}" for gap in self.gaps]
        if self.oracle.characterization:
            lines.append(f"  - {_CHARACTERIZATION_NOTE}")
        return lines or ["  - none"]

    def render(self) -> str:
        """A concise markdown summary (~10 lines)."""
        title = f"# Run report — {self.endpoint}"
        if self.route_name:
            title += f" ({self.route_name})"
        lines = [
            title,
            f"Run {self.run_id} · status: {self.status}",
            "",
            (
                f"Tests: {self.total} total — happy {self.by_type['happy']}, "
                f"negative {self.by_type['negative']}, edge {self.by_type['edge']}"
            ),
            (
                f"Outcomes: {self.outcomes['pass']} passed · "
                f"{self.outcomes['fail']} failed · {self.outcomes['error']} errored"
            ),
            "",
            "Oracle honesty:",
            f"  - {self.oracle.rule_derived} rule-derived  "
            "[strong — grounded in validation rules]",
            f"  - {self.oracle.characterization} characterization  "
            "[weak — asserts shape only; needs specs]",
            f"  - {self.oracle.spec_grounded} spec-grounded",
            "",
            "Gaps:",
            *self._gap_lines(),
        ]
        return "\n".join(lines)

    def covered_payload(self) -> dict[str, Any]:
        endpoints = [self.endpoint]
        return {
            "endpoints": endpoints,
            "route_name": self.route_name,
            "test_counts": self.by_type,
            "outcomes": self.outcomes,
            "oracle_honesty": {
                "rule_derived": self.oracle.rule_derived,
                "characterization": self.oracle.characterization,
                "spec_grounded": self.oracle.spec_grounded,
            },
        }

    def gaps_payload(self) -> dict[str, Any]:
        notes = [_CHARACTERIZATION_NOTE] if self.oracle.characterization else []
        return {"items": list(self.gaps), "notes": notes}


def summarize(
    *,
    endpoint: str,
    route_name: str | None,
    run_id: uuid.UUID,
    status: str,
    case_types: Sequence[TestType],
    oracle_sources: Sequence[OracleSource],
    outcomes: Sequence[Outcome],
    gaps: Sequence[str],
) -> RunReport:
    by_type = {
        "happy": sum(1 for t in case_types if t is TestType.HAPPY),
        "negative": sum(1 for t in case_types if t is TestType.NEGATIVE),
        "edge": sum(1 for t in case_types if t is TestType.EDGE),
    }
    outcome_counts = {
        "pass": sum(1 for o in outcomes if o is Outcome.PASS),
        "fail": sum(1 for o in outcomes if o is Outcome.FAIL),
        "error": sum(1 for o in outcomes if o is Outcome.ERROR),
    }
    oracle = OracleBreakdown(
        rule_derived=sum(1 for s in oracle_sources if s is OracleSource.RULE_DERIVED),
        characterization=sum(
            1 for s in oracle_sources if s is OracleSource.CHARACTERIZATION
        ),
        spec_grounded=sum(1 for s in oracle_sources if s is OracleSource.SPEC_GROUNDED),
    )
    return RunReport(
        endpoint=endpoint,
        route_name=route_name,
        run_id=run_id,
        status=status,
        total=len(case_types),
        by_type=by_type,
        outcomes=outcome_counts,
        oracle=oracle,
        gaps=list(gaps),
    )


def build_report(
    *,
    spec: EndpointSpec,
    generated: Sequence[GeneratedCase],
    run: Run,
    results: Sequence[Result],
    gaps: Sequence[str] = (),
) -> RunReport:
    endpoint = f"{spec.method.upper()} /{spec.uri.lstrip('/')}"
    return summarize(
        endpoint=endpoint,
        route_name=spec.route_name,
        run_id=run.id,
        status=run.status,
        case_types=[g.plan.case_type for g in generated],
        oracle_sources=[g.plan.oracle_source for g in generated],
        outcomes=[r.outcome for r in results],
        gaps=gaps,
    )


async def persist_coverage(
    *,
    session: AsyncSession,
    project_id: uuid.UUID,
    run: Run,
    report: RunReport,
) -> Coverage:
    """Persist the run's endpoint coverage row (TRD §3)."""
    repo = CoverageRepository(session)
    return await repo.add(
        Coverage(
            project_id=project_id,
            run_id=run.id,
            dimension=CoverageDimension.ENDPOINT,
            covered=report.covered_payload(),
            gaps=report.gaps_payload(),
        )
    )
