"""Model node in the finding blast path (ADR-0041) — page→endpoint→MODEL→table.

The model layer is already in the resolved journey subgraph; the assembler now
surfaces it. When the endpoint→model edge is absent the path degrades to
page→endpoint→table with no model node and no crash. Surfacing it adds no resolver
calls (the subgraph is read more fully, not re-walked).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.cross_layer import Subgraph
from app.models.enums import NodeKind, OracleSource, Outcome, TestLayer
from app.models.model_node import ModelNode
from app.reporting.finding_assembler import FindingAssembler
from app.reporting.finding_detail import location_payload
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from tests.factories import make_project, make_result, make_run, make_test_case


def _n(project_id: uuid.UUID, kind: NodeKind, name: str) -> ModelNode:
    return ModelNode(project_id=project_id, kind=kind, name=name, attributes={})


def _full_chain(project_id: uuid.UUID) -> Subgraph:
    """A journey resolving the whole page → endpoint → model → table chain."""
    page = _n(project_id, NodeKind.PAGE, "/checkout")
    return Subgraph(
        root=page,
        nodes=(
            page,
            _n(project_id, NodeKind.ENDPOINT, "POST api/orders"),
            _n(project_id, NodeKind.MODEL, "Order"),
            _n(project_id, NodeKind.TABLE, "orders"),
        ),
        edges=(),
    )


def _no_model(project_id: uuid.UUID) -> Subgraph:
    """A journey where the endpoint writes a table directly (no model node)."""
    page = _n(project_id, NodeKind.PAGE, "/checkout")
    return Subgraph(
        root=page,
        nodes=(
            page,
            _n(project_id, NodeKind.ENDPOINT, "POST api/orders"),
            _n(project_id, NodeKind.TABLE, "orders"),
        ),
        edges=(),
    )


class _CountingResolver:
    """A canned resolver that counts how many journeys it is asked for."""

    def __init__(self, by_node: dict[uuid.UUID, Subgraph]) -> None:
        self._by_node = by_node
        self.calls = 0

    async def journey(
        self, project_id: uuid.UUID, node_id: uuid.UUID, max_depth: int = 3
    ) -> Subgraph:
        self.calls += 1
        return self._by_node[node_id]


async def _seed_case_result(
    session: AsyncSession, project_id: uuid.UUID, target: uuid.UUID
):  # type: ignore[no-untyped-def]
    run = await RunRepository(session).add(make_run(project_id))
    case = await TestCaseRepository(session).add(
        make_test_case(
            project_id,
            layer=TestLayer.API,
            oracle_source=OracleSource.RULE_DERIVED,
            target_node=target,
        )
    )
    result = await ResultRepository(session).add(
        make_result(project_id, run.id, case.id, outcome=Outcome.FAIL)
    )
    return result


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


# --- assembly: the model node lands in the location ---------------------------


async def test_location_includes_model_node(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    target = uuid.uuid4()
    result = await _seed_case_result(db_session, project_id, target)

    assembler = FindingAssembler(
        db_session, resolver=_CountingResolver({target: _full_chain(project_id)})
    )
    findings = await assembler.assemble(project_id=project_id, results=[result])

    location = findings[0].location
    assert location["page"] == "/checkout"
    assert location["endpoints"] == ["POST api/orders"]
    assert location["models"] == ["Order"]  # the widened blast path
    assert location["tables"] == ["orders"]


async def test_location_degrades_without_model_edge(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    target = uuid.uuid4()
    result = await _seed_case_result(db_session, project_id, target)

    assembler = FindingAssembler(
        db_session, resolver=_CountingResolver({target: _no_model(project_id)})
    )
    findings = await assembler.assemble(project_id=project_id, results=[result])

    location = findings[0].location
    # No model node → empty list, the path is page → endpoint → table (no crash).
    assert location["models"] == []
    assert location["endpoints"] == ["POST api/orders"]
    assert location["tables"] == ["orders"]


async def test_model_node_adds_no_resolver_calls(db_session: AsyncSession) -> None:
    """Surfacing the model is a read of the existing subgraph — no extra journey."""
    project_id = await _project(db_session)
    targets = [uuid.uuid4() for _ in range(3)]
    results = [await _seed_case_result(db_session, project_id, t) for t in targets]

    resolver = _CountingResolver({t: _full_chain(project_id) for t in targets})
    assembler = FindingAssembler(db_session, resolver=resolver)
    await assembler.assemble(project_id=project_id, results=results)

    # Exactly one journey per failing result — model extraction is in-memory.
    assert resolver.calls == 3


# --- the detail payload mapper (pure) ----------------------------------------


def test_location_payload_surfaces_models_in_path_order() -> None:
    payload = location_payload(
        {
            "page": "/p",
            "endpoints": ["POST api/orders"],
            "models": ["Order"],
            "tables": ["orders"],
        }
    )
    assert payload["models"] == ["Order"]
    assert list(payload) == ["anchor", "page", "endpoints", "models", "tables"]
    # The anchor is still the deepest node (table) — model doesn't change grouping.
    assert payload["anchor"]["node_type"] == "table"


def test_location_payload_defaults_models_when_absent() -> None:
    # A pre-enrichment location (no models key) degrades cleanly to an empty list.
    payload = location_payload({"endpoints": ["GET api/x"], "tables": ["t"]})
    assert payload["models"] == []
