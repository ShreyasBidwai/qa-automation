"""Root-cause grouping + dedupe (T7.2) — fast tests.

Pure keying (deterministic, deepest-node anchor, strongest oracle) plus DB-level
grouping with injected Results and an injected resolver: failures sharing a root
cause collapse into one Finding that explains N tests, distinct root causes stay
apart, identical duplicates are deduped, group confidence is the strongest oracle
(mixed groups flagged), and assembly is project-scoped and deterministically
ordered.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.cross_layer import Subgraph
from app.models.enums import FindingLayer, NodeKind, OracleSource, Outcome, TestLayer
from app.models.model_node import ModelNode
from app.reporting.finding_assembler import (
    FindingAssembler,
    root_cause_key,
    strongest_oracle,
)
from app.repositories.finding_repository import FindingRepository
from app.repositories.finding_result_repository import FindingResultRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from tests.factories import make_project, make_result, make_run, make_test_case

# --- pure keying -------------------------------------------------------------


def test_root_cause_key_is_deterministic() -> None:
    loc = {"page": None, "endpoints": ["POST api/checkout"], "tables": []}
    a = root_cause_key(loc, Outcome.FAIL, {})
    b = root_cause_key(dict(loc), Outcome.FAIL, {})
    assert a == b  # pure: same inputs → same key
    assert a == "endpoint=POST api/checkout#fail"


def test_anchor_prefers_deepest_node_table_over_endpoint_over_page() -> None:
    page_only = {"page": "/checkout", "endpoints": [], "tables": []}
    with_ep = {"page": "/checkout", "endpoints": ["POST api/checkout"], "tables": []}
    with_table = {
        "page": "/checkout",
        "endpoints": ["POST api/checkout"],
        "tables": ["orders"],
    }
    assert root_cause_key(page_only, Outcome.FAIL, {}).startswith("page=/checkout#")
    assert root_cause_key(with_ep, Outcome.FAIL, {}).startswith(
        "endpoint=POST api/checkout#"
    )
    assert root_cause_key(with_table, Outcome.FAIL, {}).startswith("table=orders#")
    # The three distinct anchors yield three distinct keys.
    keys = {
        root_cause_key(page_only, Outcome.FAIL, {}),
        root_cause_key(with_ep, Outcome.FAIL, {}),
        root_cause_key(with_table, Outcome.FAIL, {}),
    }
    assert len(keys) == 3


def test_signature_separates_failure_shapes_and_is_order_stable() -> None:
    loc = {"endpoints": ["e"], "tables": []}
    fail = root_cause_key(loc, Outcome.FAIL, {})
    error = root_cause_key(loc, Outcome.ERROR, {})
    assert fail != error  # outcome is part of the signature
    expected_a = {"status": 500, "assertions": [{"kind": "body"}, {"kind": "status"}]}
    expected_b = {"status": 500, "assertions": [{"kind": "status"}, {"kind": "body"}]}
    # Assertion kinds are sorted → key independent of assertion ordering.
    assert root_cause_key(loc, Outcome.FAIL, expected_a) == root_cause_key(
        loc, Outcome.FAIL, expected_b
    )
    assert "status=500" in root_cause_key(loc, Outcome.FAIL, expected_a)
    assert root_cause_key(loc, Outcome.FAIL, expected_a) != fail


def test_unlocated_failure_still_keys() -> None:
    assert root_cause_key({}, Outcome.ERROR, {}) == "unlocated#error"


def test_strongest_oracle_ranks_spec_over_rule_over_characterization() -> None:
    assert (
        strongest_oracle([OracleSource.CHARACTERIZATION, OracleSource.RULE_DERIVED])
        is OracleSource.RULE_DERIVED
    )
    assert (
        strongest_oracle([OracleSource.RULE_DERIVED, OracleSource.SPEC_GROUNDED])
        is OracleSource.SPEC_GROUNDED
    )
    assert (
        strongest_oracle([OracleSource.CHARACTERIZATION])
        is OracleSource.CHARACTERIZATION
    )


# --- DB grouping fixtures ----------------------------------------------------


class _FixedResolver:
    """Returns a fixed endpoint-only journey per target node id."""

    def __init__(self, endpoints: dict[uuid.UUID, str]) -> None:
        self._endpoints = endpoints

    async def journey(
        self, project_id: uuid.UUID, node_id: uuid.UUID, max_depth: int = 3
    ) -> Subgraph:
        endpoint = ModelNode(
            project_id=project_id,
            kind=NodeKind.ENDPOINT,
            name=self._endpoints[node_id],
            attributes={},
        )
        return Subgraph(root=endpoint, nodes=(endpoint,), edges=())


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


async def _run_id(session: AsyncSession, project_id: uuid.UUID) -> uuid.UUID:
    return (await RunRepository(session).add(make_run(project_id))).id


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


# --- DB grouping tests -------------------------------------------------------


async def test_twelve_failures_on_one_endpoint_become_one_finding(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    run_id = await _run_id(db_session, project_id)
    endpoint_node = uuid.uuid4()
    results = []
    for _ in range(12):  # twelve DISTINCT tests, all hitting the same endpoint
        case = await _case(
            db_session, project_id, layer=TestLayer.UI, target_node=endpoint_node
        )
        results.append(
            await _result(db_session, project_id, run_id, case.id, outcome=Outcome.FAIL)
        )

    resolver = _FixedResolver({endpoint_node: "POST api/checkout"})
    findings = await FindingAssembler(db_session, resolver=resolver).assemble(
        project_id=project_id, results=results
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.explains_count == 12  # explains all twelve
    assert finding.layer is FindingLayer.UI
    assert "endpoint=POST api/checkout" in finding.root_cause_key
    members = await FindingResultRepository(db_session).list_for_finding(
        project_id, finding.id
    )
    assert {m.result_id for m in members} == {r.id for r in results}  # all joined


async def test_distinct_root_causes_become_distinct_findings(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    run_id = await _run_id(db_session, project_id)
    node_a, node_b = uuid.uuid4(), uuid.uuid4()
    case_a = await _case(db_session, project_id, target_node=node_a)
    case_b = await _case(db_session, project_id, target_node=node_b)
    results = [
        await _result(db_session, project_id, run_id, case_a.id, outcome=Outcome.FAIL),
        await _result(db_session, project_id, run_id, case_b.id, outcome=Outcome.FAIL),
    ]

    resolver = _FixedResolver({node_a: "GET api/a", node_b: "GET api/b"})
    findings = await FindingAssembler(db_session, resolver=resolver).assemble(
        project_id=project_id, results=results
    )

    assert len(findings) == 2
    assert all(f.explains_count == 1 for f in findings)
    assert len({f.root_cause_key for f in findings}) == 2


async def test_identical_duplicate_failures_are_deduped(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    run_id = await _run_id(db_session, project_id)
    node = uuid.uuid4()
    case = await _case(db_session, project_id, target_node=node)
    # The SAME test failing twice in the run (a re-run / flake) — one bug, one test.
    duplicate_results = [
        await _result(db_session, project_id, run_id, case.id, outcome=Outcome.FAIL),
        await _result(db_session, project_id, run_id, case.id, outcome=Outcome.FAIL),
    ]

    resolver = _FixedResolver({node: "GET api/thing"})
    findings = await FindingAssembler(db_session, resolver=resolver).assemble(
        project_id=project_id, results=duplicate_results
    )

    assert len(findings) == 1
    assert findings[0].explains_count == 1  # deduped: counts the test once
    members = await FindingResultRepository(db_session).list_for_finding(
        project_id, findings[0].id
    )
    assert len(members) == 1


async def test_group_confidence_is_strongest_oracle_and_flags_mixed(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    run_id = await _run_id(db_session, project_id)
    node = uuid.uuid4()
    weak = await _case(
        db_session,
        project_id,
        target_node=node,
        oracle_source=OracleSource.CHARACTERIZATION,
    )
    strong = await _case(
        db_session,
        project_id,
        target_node=node,
        oracle_source=OracleSource.RULE_DERIVED,
    )
    results = [
        await _result(db_session, project_id, run_id, weak.id, outcome=Outcome.FAIL),
        await _result(db_session, project_id, run_id, strong.id, outcome=Outcome.FAIL),
    ]

    resolver = _FixedResolver({node: "POST api/orders"})
    findings = await FindingAssembler(db_session, resolver=resolver).assemble(
        project_id=project_id, results=results
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.explains_count == 2
    # One rule-derived failure makes the whole group high-confidence...
    assert finding.oracle_source is OracleSource.RULE_DERIVED
    # ...but the group is flagged mixed because members disagree on oracle tier.
    assert finding.confidence_mixed is True


async def test_uniform_group_is_not_flagged_mixed(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    run_id = await _run_id(db_session, project_id)
    node = uuid.uuid4()
    cases = [
        await _case(
            db_session,
            project_id,
            target_node=node,
            oracle_source=OracleSource.CHARACTERIZATION,
        )
        for _ in range(3)
    ]
    results = [
        await _result(db_session, project_id, run_id, c.id, outcome=Outcome.FAIL)
        for c in cases
    ]

    resolver = _FixedResolver({node: "GET api/list"})
    findings = await FindingAssembler(db_session, resolver=resolver).assemble(
        project_id=project_id, results=results
    )

    assert len(findings) == 1
    assert findings[0].confidence_mixed is False
    assert findings[0].oracle_source is OracleSource.CHARACTERIZATION


async def test_grouping_is_project_scoped_and_deterministically_ordered(
    db_session: AsyncSession,
) -> None:
    project_a = await _project(db_session)
    project_b = await _project(db_session)
    run_id = await _run_id(db_session, project_a)
    node_z, node_a = uuid.uuid4(), uuid.uuid4()
    case_z = await _case(db_session, project_a, target_node=node_z)
    case_a = await _case(db_session, project_a, target_node=node_a)
    results = [
        await _result(db_session, project_a, run_id, case_z.id, outcome=Outcome.FAIL),
        await _result(db_session, project_a, run_id, case_a.id, outcome=Outcome.FAIL),
    ]

    # Names chosen so root_cause_key ordering ("GET api/aaa" < "GET api/zzz")
    # differs from insertion order, proving the deterministic sort.
    resolver = _FixedResolver({node_z: "GET api/zzz", node_a: "GET api/aaa"})
    findings = await FindingAssembler(db_session, resolver=resolver).assemble(
        project_id=project_a, results=results
    )
    assert all(f.project_id == project_a for f in findings)

    repo = FindingRepository(db_session)
    listed = await repo.list_for_run(project_a, run_id)
    keys = [f.root_cause_key for f in listed]
    assert keys == sorted(keys)  # deterministic, content-ordered
    assert "api/aaa" in keys[0] and "api/zzz" in keys[1]
    assert await repo.list_for_run(project_b, run_id) == []  # no cross-project bleed
