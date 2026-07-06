"""FindingAssembler — fast tests (seeded results + an injected resolver).

A non-passing result becomes a Finding with the right layer, confidence
(oracle_source), evidence, expected oracle, and cross-layer location; a passing
result produces nothing; assembly is project-scoped; a result whose case is not
in the project is rejected; a resolver failure degrades to an empty location.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.cross_layer import NodeNotFoundError, Subgraph
from app.models.enums import FindingLayer, NodeKind, OracleSource, Outcome, TestLayer
from app.models.model_node import ModelNode
from app.reporting.errors import FindingAssemblyError
from app.reporting.finding_assembler import FindingAssembler
from app.repositories.finding_repository import FindingRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from tests.factories import make_project, make_result, make_run, make_test_case


class _FakeResolver:
    """Returns a canned journey subgraph per target node (no real graph)."""

    def __init__(self, by_node: dict[uuid.UUID, Subgraph]) -> None:
        self._by_node = by_node

    async def journey(
        self, project_id: uuid.UUID, node_id: uuid.UUID, max_depth: int = 3
    ) -> Subgraph:
        return self._by_node[node_id]


class _RaisingResolver:
    async def journey(
        self, project_id: uuid.UUID, node_id: uuid.UUID, max_depth: int = 3
    ) -> Subgraph:
        raise NodeNotFoundError("target node is gone")


def _journey(project_id: uuid.UUID) -> Subgraph:
    def _n(kind: NodeKind, name: str) -> ModelNode:
        return ModelNode(project_id=project_id, kind=kind, name=name, attributes={})

    page = _n(NodeKind.PAGE, "/checkout")
    return Subgraph(
        root=page,
        nodes=(
            page,
            _n(NodeKind.ENDPOINT, "POST api/checkout"),
            _n(NodeKind.TABLE, "orders"),
        ),
        edges=(),
    )


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


async def _run_id(session: AsyncSession, project_id: uuid.UUID) -> uuid.UUID:
    run = await RunRepository(session).add(make_run(project_id))
    return run.id


async def _case(session: AsyncSession, project_id: uuid.UUID, **overrides: object):
    return await TestCaseRepository(session).add(
        make_test_case(project_id, **overrides)
    )


async def _result(
    session: AsyncSession,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    case_id: uuid.UUID,
    **overrides: object,
):
    return await ResultRepository(session).add(
        make_result(project_id, run_id, case_id, **overrides)
    )


async def test_failing_result_becomes_a_finding(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    run_id = await _run_id(db_session, project_id)
    target = uuid.uuid4()
    case = await _case(
        db_session,
        project_id,
        layer=TestLayer.UI,
        oracle_source=OracleSource.CHARACTERIZATION,
        target_node=target,
        expected={"assertions": [{"kind": "recorded_state"}]},
    )
    result = await _result(
        db_session,
        project_id,
        run_id,
        case.id,
        outcome=Outcome.FAIL,
        evidence_ref="ev/trace.zip",
    )

    assembler = FindingAssembler(
        db_session, resolver=_FakeResolver({target: _journey(project_id)})
    )
    findings = await assembler.assemble(project_id=project_id, results=[result])

    assert len(findings) == 1
    finding = findings[0]
    assert finding.layer is FindingLayer.UI
    assert finding.oracle_source is OracleSource.CHARACTERIZATION  # confidence
    assert finding.evidence_ref == "ev/trace.zip"
    assert finding.expected == {"assertions": [{"kind": "recorded_state"}]}
    assert finding.location["page"] == "/checkout"
    assert "POST api/checkout" in finding.location["endpoints"]
    assert "orders" in finding.location["tables"]
    assert finding.status == "open" and finding.severity == "unset"  # placeholders
    assert finding.run_id == run_id
    assert finding.result_id == result.id
    assert finding.project_id == project_id


async def test_errored_result_becomes_an_errored_finding_clearly_labeled(
    db_session: AsyncSession,
) -> None:
    # An ERROR result (test could not complete — e.g. an unparseable JUnit) is still
    # surfaced as a finding, but labeled an "errored test" (oracle-inconclusive), NOT
    # a "failure" (an asserted defect). The diagnostic rides on the linked result.
    project_id = await _project(db_session)
    run_id = await _run_id(db_session, project_id)
    target = uuid.uuid4()
    case = await _case(
        db_session,
        project_id,
        layer=TestLayer.API,
        oracle_source=OracleSource.RULE_DERIVED,
        target_node=target,
        expected={"status": 422},
    )
    result = await _result(
        db_session,
        project_id,
        run_id,
        case.id,
        outcome=Outcome.ERROR,
        message="test errored — could not produce results (runner exit 255); …",
        evidence_ref="ev/junit.xml",
    )

    findings = await FindingAssembler(
        db_session, resolver=_FakeResolver({target: _journey(project_id)})
    ).assemble(project_id=project_id, results=[result])

    assert len(findings) == 1
    finding = findings[0]
    assert "errored test" in finding.title  # clearly labeled as inconclusive
    assert "failure" not in finding.title  # NOT a real asserted defect
    assert finding.result_id == result.id  # the diagnostic is on the linked result


async def test_passing_result_produces_no_finding(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    run_id = await _run_id(db_session, project_id)
    case = await _case(db_session, project_id, layer=TestLayer.API)
    result = await _result(
        db_session, project_id, run_id, case.id, outcome=Outcome.PASS
    )

    findings = await FindingAssembler(db_session, resolver=_FakeResolver({})).assemble(
        project_id=project_id, results=[result]
    )

    assert findings == []


async def test_assembly_is_project_scoped(db_session: AsyncSession) -> None:
    project_a = await _project(db_session)
    project_b = await _project(db_session)
    run_id = await _run_id(db_session, project_a)
    case = await _case(db_session, project_a, layer=TestLayer.API, target_node=None)
    result = await _result(db_session, project_a, run_id, case.id, outcome=Outcome.FAIL)

    findings = await FindingAssembler(db_session, resolver=_FakeResolver({})).assemble(
        project_id=project_a, results=[result]
    )

    assert findings and all(f.project_id == project_a for f in findings)
    assert findings[0].location == {}  # no target node → no location
    repo = FindingRepository(db_session)
    assert len(await repo.list_for_run(project_a, run_id)) == 1
    assert await repo.list_for_run(project_b, run_id) == []  # no cross-project bleed


async def test_unresolved_target_names_the_endpoint_from_the_case_key(
    db_session: AsyncSession,
) -> None:
    # A case with no target_node (never linked a Brain node) still names the failing
    # endpoint from its stable case_key — "at GET /login/apple", not "unknown target"
    # (ADR-0063 reporting fidelity).
    project_id = await _project(db_session)
    run_id = await _run_id(db_session, project_id)
    case = await _case(
        db_session,
        project_id,
        layer=TestLayer.API,
        target_node=None,
        case_key="GET /login/apple::happy::happy",
    )
    result = await _result(
        db_session, project_id, run_id, case.id, outcome=Outcome.FAIL
    )

    findings = await FindingAssembler(db_session, resolver=_FakeResolver({})).assemble(
        project_id=project_id, results=[result]
    )

    assert len(findings) == 1
    assert findings[0].location["endpoints"] == ["GET /login/apple"]
    assert "GET /login/apple" in findings[0].title
    assert "unknown target" not in findings[0].title


async def test_result_for_a_foreign_case_is_rejected(db_session: AsyncSession) -> None:
    project_a = await _project(db_session)
    project_b = await _project(db_session)
    run_id = await _run_id(db_session, project_a)
    foreign_case = await _case(db_session, project_b, layer=TestLayer.API)
    # A result in A pointing at B's case (a tenancy violation).
    result = await _result(
        db_session, project_a, run_id, foreign_case.id, outcome=Outcome.FAIL
    )

    with pytest.raises(FindingAssemblyError):
        await FindingAssembler(db_session, resolver=_FakeResolver({})).assemble(
            project_id=project_a, results=[result]
        )


async def test_errored_result_with_integration_layer_and_lost_node(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    run_id = await _run_id(db_session, project_id)
    case = await _case(
        db_session, project_id, layer=TestLayer.INTEGRATION, target_node=uuid.uuid4()
    )
    result = await _result(
        db_session, project_id, run_id, case.id, outcome=Outcome.ERROR
    )

    findings = await FindingAssembler(db_session, resolver=_RaisingResolver()).assemble(
        project_id=project_id, results=[result]
    )

    assert len(findings) == 1  # an erroring result is a finding too
    assert findings[0].layer is FindingLayer.API  # integration maps to api
    assert findings[0].location == {}  # resolver failure → empty location
