"""RunReport correctness — counts, oracle-honesty breakdown, gaps (PRD §10)."""

from __future__ import annotations

import uuid

from app.generation.plan import plan_cases
from app.models.enums import OracleSource, Outcome, TestType
from app.reporting.report import summarize


def _report_from_known_set():
    return summarize(
        endpoint="POST /api/users",
        route_name="users.store",
        run_id=uuid.UUID("00000000-0000-0000-0000-0000000000aa"),
        status="failed",
        case_types=[
            TestType.HAPPY,
            TestType.NEGATIVE,
            TestType.NEGATIVE,
            TestType.EDGE,
        ],
        oracle_sources=[
            OracleSource.CHARACTERIZATION,
            OracleSource.RULE_DERIVED,
            OracleSource.RULE_DERIVED,
            OracleSource.RULE_DERIVED,
        ],
        outcomes=[Outcome.PASS, Outcome.PASS, Outcome.FAIL, Outcome.ERROR],
        gaps=["country_id_exists_missing: dependency seeding unavailable"],
    )


def test_counts_outcomes_and_oracle_breakdown() -> None:
    report = _report_from_known_set()
    assert report.total == 4
    assert report.by_type == {"happy": 1, "negative": 2, "edge": 1}
    assert report.outcomes == {"pass": 2, "fail": 1, "error": 1}
    assert report.oracle.rule_derived == 3
    assert report.oracle.characterization == 1
    assert report.oracle.spec_grounded == 0


def test_render_is_concise_and_oracle_honest() -> None:
    text = _report_from_known_set().render()
    lines = text.splitlines()
    assert lines[0] == "# Run report — POST /api/users (users.store)"
    assert "status: failed" in text
    # The oracle-honesty breakdown is explicit and labels strong vs weak.
    assert "3 rule-derived  [strong" in text
    assert "1 characterization  [weak" in text
    assert "0 spec-grounded" in text
    # Gaps: the explicit gap AND the standing characterization honesty note.
    assert "country_id_exists_missing" in text
    assert "characterization-only" in text
    # Concise — roughly ten lines, not a wall of text.
    assert len(lines) <= 16


def test_gaps_note_only_appears_with_characterization() -> None:
    report = summarize(
        endpoint="POST /api/users",
        route_name=None,
        run_id=uuid.uuid4(),
        status="passed",
        case_types=[TestType.NEGATIVE],
        oracle_sources=[OracleSource.RULE_DERIVED],
        outcomes=[Outcome.PASS],
        gaps=[],
    )
    assert report.gaps_payload()["notes"] == []
    assert "  - none" in report.render()


def test_breakdown_matches_the_generated_plan(endpoint_spec: object) -> None:
    cases = plan_cases(endpoint_spec)  # type: ignore[arg-type]
    report = summarize(
        endpoint="POST /api/users",
        route_name="users.store",
        run_id=uuid.uuid4(),
        status="passed",
        case_types=[c.case_type for c in cases],
        oracle_sources=[c.oracle_source for c in cases],
        outcomes=[Outcome.PASS] * len(cases),
        gaps=[],
    )
    assert report.total == 14
    assert report.by_type == {"happy": 1, "negative": 10, "edge": 3}
    # Oracle honesty is the differentiator: 13 strong, 1 weak, 0 fabricated.
    assert report.oracle.rule_derived == 13
    assert report.oracle.characterization == 1
    assert report.oracle.spec_grounded == 0
