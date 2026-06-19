"""Severity scoring + triage ranking (T7.3) — fast tests.

Pure scoring (blast × failure shape → severity, ADR-0022 thresholds) and ranking
(severity desc, confidence desc, root_cause_key), plus DB integration with
injected findings and an injected impact resolver: severity is scored from the
anchor's blast radius and persisted, a run's findings come back in triage order,
degrade paths fall back to the failure shape, and everything is project-scoped.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.cross_layer import Impact, NodeNotFoundError
from app.models.enums import FindingLayer, NodeKind, OracleSource, Outcome, Severity
from app.models.finding import Finding
from app.models.model_node import ModelNode
from app.reporting.scoring import (
    SeverityScorer,
    blast_radius,
    rank_findings,
    score_severity,
    severity_rank,
)
from app.repositories.finding_repository import FindingRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from tests.factories import make_project, make_result, make_run, make_test_case


def _node(project_id: uuid.UUID, kind: NodeKind, name: str) -> ModelNode:
    return ModelNode(project_id=project_id, kind=kind, name=name, attributes={})


def _mk_finding(severity: str, oracle: OracleSource, key: str) -> Finding:
    """An in-memory finding carrying just what ranking reads (no DB)."""
    return Finding(severity=severity, oracle_source=oracle, root_cause_key=key)


# --- pure scoring ------------------------------------------------------------


def test_high_blast_rule_derived_is_critical() -> None:
    assert (
        score_severity(5, Outcome.FAIL, OracleSource.RULE_DERIVED) is Severity.CRITICAL
    )


def test_isolated_characterization_is_minor() -> None:
    assert (
        score_severity(0, Outcome.FAIL, OracleSource.CHARACTERIZATION) is Severity.MINOR
    )


def test_in_between_cases_are_major() -> None:
    # rule violation but only locally depended on
    assert score_severity(2, Outcome.FAIL, OracleSource.RULE_DERIVED) is Severity.MAJOR
    # soft mismatch but widely depended on
    assert (
        score_severity(5, Outcome.FAIL, OracleSource.CHARACTERIZATION) is Severity.MAJOR
    )
    # hard error on an isolated node
    assert (
        score_severity(0, Outcome.ERROR, OracleSource.CHARACTERIZATION)
        is Severity.MAJOR
    )


def test_error_outranks_soft_mismatch_at_equal_blast() -> None:
    for blast in (0, 2, 5):
        hard = score_severity(blast, Outcome.ERROR, OracleSource.CHARACTERIZATION)
        soft = score_severity(blast, Outcome.FAIL, OracleSource.CHARACTERIZATION)
        assert severity_rank(hard.value) > severity_rank(soft.value)


def test_blast_radius_counts_callers_writes_and_roles() -> None:
    project_id = uuid.uuid4()
    impact = Impact(
        node=_node(project_id, NodeKind.TABLE, "orders"),
        callers=(_node(project_id, NodeKind.PAGE, "p1"),),
        writes=(_node(project_id, NodeKind.TABLE, "t1"),),
        roles=(
            _node(project_id, NodeKind.ROLE, "admin"),
            _node(project_id, NodeKind.ROLE, "user"),
        ),
        edges=(),
    )
    assert blast_radius(impact) == 4


# --- pure ranking ------------------------------------------------------------


def test_ranking_orders_by_severity_then_confidence_then_key() -> None:
    crit = _mk_finding("critical", OracleSource.RULE_DERIVED, "b")
    major_rule = _mk_finding("major", OracleSource.RULE_DERIVED, "a")
    major_char = _mk_finding("major", OracleSource.CHARACTERIZATION, "a")
    # spec-grounded confidence does NOT lift a minor above a major (severity wins)
    minor = _mk_finding("minor", OracleSource.SPEC_GROUNDED, "z")

    ranked = rank_findings([minor, major_char, crit, major_rule])

    assert ranked == [crit, major_rule, major_char, minor]


def test_ranking_ties_broken_deterministically_by_root_cause_key() -> None:
    a = _mk_finding("critical", OracleSource.RULE_DERIVED, "aaa")
    z = _mk_finding("critical", OracleSource.RULE_DERIVED, "zzz")
    assert rank_findings([z, a]) == [a, z]


def test_unset_severity_sinks_below_scored_findings() -> None:
    scored = _mk_finding("minor", OracleSource.CHARACTERIZATION, "a")
    unset = _mk_finding("unset", OracleSource.SPEC_GROUNDED, "a")
    assert rank_findings([unset, scored]) == [scored, unset]


# --- DB fixtures -------------------------------------------------------------


class _FakeImpact:
    """Returns an impact whose blast == a fixed count per anchor node id."""

    def __init__(
        self,
        blast_by_node: dict[uuid.UUID, int],
        *,
        raises: frozenset[uuid.UUID] = frozenset(),
    ) -> None:
        self._blast = blast_by_node
        self._raises = raises

    async def impact(self, project_id: uuid.UUID, node_id: uuid.UUID) -> Impact:
        if node_id in self._raises:
            raise NodeNotFoundError(f"node {node_id} gone")
        count = self._blast.get(node_id, 0)
        return Impact(
            node=_node(project_id, NodeKind.ENDPOINT, "anchor"),
            callers=tuple(
                _node(project_id, NodeKind.PAGE, f"p{i}") for i in range(count)
            ),
            writes=(),
            roles=(),
            edges=(),
        )


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


async def _run_id(session: AsyncSession, project_id: uuid.UUID) -> uuid.UUID:
    return (await RunRepository(session).add(make_run(project_id))).id


async def _result_for(
    session: AsyncSession,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    target_node: uuid.UUID | None,
    oracle: OracleSource,
    outcome: Outcome,
):
    case = await TestCaseRepository(session).add(
        make_test_case(project_id, target_node=target_node, oracle_source=oracle)
    )
    return await ResultRepository(session).add(
        make_result(project_id, run_id, case.id, outcome=outcome)
    )


async def _finding_for(
    session: AsyncSession,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    result_id: uuid.UUID,
    *,
    oracle: OracleSource,
    key: str,
):
    return await FindingRepository(session).add(
        Finding(
            project_id=project_id,
            run_id=run_id,
            result_id=result_id,
            root_cause_key=key,
            explains_count=1,
            title="finding",
            layer=FindingLayer.API,
            oracle_source=oracle,
            confidence_mixed=False,
            expected={},
            evidence_ref=None,
            location={},
            severity="unset",
            status="open",
        )
    )


# --- DB scoring --------------------------------------------------------------


async def test_scores_and_persists_critical_severity(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    run_id = await _run_id(db_session, project_id)
    node = uuid.uuid4()
    result = await _result_for(
        db_session,
        project_id,
        run_id,
        target_node=node,
        oracle=OracleSource.RULE_DERIVED,
        outcome=Outcome.FAIL,
    )
    finding = await _finding_for(
        db_session,
        project_id,
        run_id,
        result.id,
        oracle=OracleSource.RULE_DERIVED,
        key="k",
    )

    scorer = SeverityScorer(db_session, impact_resolver=_FakeImpact({node: 5}))
    await scorer.score(project_id, finding)

    assert finding.severity == "critical"  # wide blast + rule-derived
    reloaded = await FindingRepository(db_session).get(project_id, finding.id)
    assert reloaded is not None and reloaded.severity == "critical"  # persisted


async def test_blast_lookup_failure_degrades_to_failure_shape(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    run_id = await _run_id(db_session, project_id)
    node = uuid.uuid4()
    result = await _result_for(
        db_session,
        project_id,
        run_id,
        target_node=node,
        oracle=OracleSource.CHARACTERIZATION,
        outcome=Outcome.FAIL,
    )
    finding = await _finding_for(
        db_session,
        project_id,
        run_id,
        result.id,
        oracle=OracleSource.CHARACTERIZATION,
        key="k",
    )

    # The anchor node is gone from the Brain → blast 0; soft mismatch → minor.
    scorer = SeverityScorer(
        db_session, impact_resolver=_FakeImpact({}, raises=frozenset({node}))
    )
    await scorer.score(project_id, finding)
    assert finding.severity == "minor"


async def test_missing_target_node_scores_from_outcome_only(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    run_id = await _run_id(db_session, project_id)
    result = await _result_for(
        db_session,
        project_id,
        run_id,
        target_node=None,  # no anchor → blast 0
        oracle=OracleSource.CHARACTERIZATION,
        outcome=Outcome.ERROR,  # hard failure
    )
    finding = await _finding_for(
        db_session,
        project_id,
        run_id,
        result.id,
        oracle=OracleSource.CHARACTERIZATION,
        key="k",
    )

    scorer = SeverityScorer(db_session, impact_resolver=_FakeImpact({}))
    await scorer.score(project_id, finding)
    assert finding.severity == "major"  # hard error, isolated → major


async def test_score_handles_a_finding_with_no_result(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    run_id = await _run_id(db_session, project_id)
    # An in-memory finding pointing at a non-existent result (defensive path).
    finding = Finding(
        project_id=project_id,
        run_id=run_id,
        result_id=uuid.uuid4(),
        root_cause_key="k",
        explains_count=1,
        title="finding",
        layer=FindingLayer.API,
        oracle_source=OracleSource.CHARACTERIZATION,
        confidence_mixed=False,
        expected={},
        location={},
        severity="unset",
        status="open",
    )

    scorer = SeverityScorer(db_session, impact_resolver=_FakeImpact({}))
    await scorer.score(project_id, finding)
    assert finding.severity == "minor"  # no result → FAIL + char, blast 0


async def test_score_run_ranks_and_is_project_scoped(
    db_session: AsyncSession,
) -> None:
    project_a = await _project(db_session)
    project_b = await _project(db_session)
    run_id = await _run_id(db_session, project_a)
    node_crit, node_minor = uuid.uuid4(), uuid.uuid4()

    crit_result = await _result_for(
        db_session,
        project_a,
        run_id,
        target_node=node_crit,
        oracle=OracleSource.RULE_DERIVED,
        outcome=Outcome.FAIL,
    )
    minor_result = await _result_for(
        db_session,
        project_a,
        run_id,
        target_node=node_minor,
        oracle=OracleSource.CHARACTERIZATION,
        outcome=Outcome.FAIL,
    )
    # "zzz" key on the critical one proves severity beats the key tie-break.
    crit = await _finding_for(
        db_session,
        project_a,
        run_id,
        crit_result.id,
        oracle=OracleSource.RULE_DERIVED,
        key="zzz",
    )
    minor = await _finding_for(
        db_session,
        project_a,
        run_id,
        minor_result.id,
        oracle=OracleSource.CHARACTERIZATION,
        key="aaa",
    )

    scorer = SeverityScorer(
        db_session, impact_resolver=_FakeImpact({node_crit: 5, node_minor: 0})
    )
    ranked = await scorer.score_run(project_a, run_id)

    assert [f.severity for f in ranked] == ["critical", "minor"]
    assert [f.id for f in ranked] == [crit.id, minor.id]  # critical first
    # Computed-on-read ranking agrees, and another project sees nothing.
    assert [f.id for f in await scorer.ranked_for_run(project_a, run_id)] == [
        crit.id,
        minor.id,
    ]
    assert await scorer.ranked_for_run(project_b, run_id) == []
