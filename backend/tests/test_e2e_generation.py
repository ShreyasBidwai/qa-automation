"""E2E generation — fast tests (deterministic plan, stub render, lifecycle).

Plan: a journey with a page+form yields a happy case + a negative per required
field, oracle-tagged (required → rule-derived, recorded state → characterization).
Mutation gate: a tautological assertion is rejected. Render: the stub spec is
wrapped with the deterministic oracle-provenance header. Lifecycle: cases persist
through CaseMergeService with provenance, and a re-gen over a human-edited case
yields a proposal, not a clobber.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.stub import StubAIProvider
from app.brain.cross_layer import Subgraph
from app.generation.e2e_generator import E2EGenerator
from app.generation.e2e_plan import (
    E2EAssertion,
    PlannedE2ECase,
    build_e2e_plan,
    e2e_case_key,
)
from app.generation.e2e_render import render_e2e_spec
from app.generation.errors import E2EPlanError, MutationGateError
from app.generation.mutation_gate import enforce_mutation_gate, is_tautological
from app.models.enums import CaseOrigin, NodeKind, OracleSource, TestLayer, TestType
from app.models.model_node import ModelNode
from app.repositories.node_repository import NodeRepository
from app.services.test_case_service import TestCaseService
from tests.factories import make_node, make_project

_FORM = {
    "action": "/api/orders",
    "method": "POST",
    "fields": [
        {"name": "email", "type": "email", "required": True},
        {"name": "note", "type": "text", "required": False},
    ],
}


def _page_node(path: str = "/orders", forms: list[dict] | None = None) -> ModelNode:
    return ModelNode(
        project_id=uuid.uuid4(),
        kind=NodeKind.PAGE,
        name=path,
        attributes={"path": path, "title": "Orders", "forms": forms or []},
    )


def _journey(page: ModelNode) -> Subgraph:
    return Subgraph(root=page, nodes=(page,), edges=())


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


async def _seed_page(
    session: AsyncSession, project_id: uuid.UUID, path: str, forms: list[dict]
) -> ModelNode:
    return await NodeRepository(session).add(
        make_node(
            project_id,
            kind=NodeKind.PAGE,
            name=path,
            attributes={"path": path, "title": "Orders", "forms": forms},
        )
    )


# --- deterministic plan + oracle tagging -------------------------------------


def test_plan_has_happy_and_required_negative_with_oracle_tags() -> None:
    plan = build_e2e_plan(_journey(_page_node(forms=[_FORM])))
    by_name = {c.name: c for c in plan}

    assert set(by_name) == {"happy", "email_required_missing"}

    happy = by_name["happy"]
    assert happy.oracle_source is OracleSource.CHARACTERIZATION
    assert happy.case_type is TestType.E2E
    assert [s.action for s in happy.steps] == ["navigate", "fill", "fill", "submit"]
    assert happy.assertions[0].kind == "recorded_state"
    assert happy.assertions[0].oracle_source is OracleSource.CHARACTERIZATION

    neg = by_name["email_required_missing"]
    assert neg.oracle_source is OracleSource.RULE_DERIVED
    # The empty (required) field is NOT filled; the other field is.
    filled = {s.target for s in neg.steps if s.action == "fill"}
    assert filled == {"note"}
    assert neg.assertions[0].kind == "validation_error"
    assert neg.assertions[0].target == "email"
    assert neg.assertions[0].oracle_source is OracleSource.RULE_DERIVED


def test_plan_for_formless_page_is_a_single_happy_case() -> None:
    plan = build_e2e_plan(_journey(_page_node(path="/about", forms=[])))
    assert len(plan) == 1
    assert plan[0].name == "happy"
    assert [s.action for s in plan[0].steps] == ["navigate"]  # no fill/submit
    assert plan[0].assertions[0].oracle_source is OracleSource.CHARACTERIZATION


def test_plan_root_must_be_a_page() -> None:
    endpoint = ModelNode(
        project_id=uuid.uuid4(),
        kind=NodeKind.ENDPOINT,
        name="GET api/orders",
        attributes={"method": "GET", "uri": "api/orders"},
    )
    with pytest.raises(E2EPlanError):
        build_e2e_plan(_journey(endpoint))


def test_case_key_is_deterministic_and_distinct() -> None:
    assert e2e_case_key("/orders", "happy") == e2e_case_key("orders", "happy")
    assert e2e_case_key("/orders", "happy") != e2e_case_key("/orders", "negative")


# --- mutation-kill gate ------------------------------------------------------


def test_mutation_gate_rejects_tautological_assertion() -> None:
    tautological = PlannedE2ECase(
        name="smoke",
        case_type=TestType.E2E,
        page_path="/x",
        steps=(),
        assertions=(E2EAssertion("loaded", "", OracleSource.CHARACTERIZATION),),
        oracle_source=OracleSource.CHARACTERIZATION,
    )
    with pytest.raises(MutationGateError):
        enforce_mutation_gate([tautological])

    # A case with no assertions at all is also rejected.
    no_assertions = PlannedE2ECase(
        name="empty",
        case_type=TestType.E2E,
        page_path="/x",
        steps=(),
        assertions=(),
        oracle_source=OracleSource.CHARACTERIZATION,
    )
    with pytest.raises(MutationGateError):
        enforce_mutation_gate([no_assertions])

    char = OracleSource.CHARACTERIZATION
    assert is_tautological(E2EAssertion("loaded", "x", char))
    assert is_tautological(E2EAssertion("recorded_state", "", char))
    assert not is_tautological(
        E2EAssertion("validation_error", "email", OracleSource.RULE_DERIVED)
    )


def test_mutation_gate_passes_a_real_plan() -> None:
    enforce_mutation_gate(build_e2e_plan(_journey(_page_node(forms=[_FORM]))))


# --- AI render ---------------------------------------------------------------


def test_render_wraps_stub_body_with_oracle_header() -> None:
    plan = build_e2e_plan(_journey(_page_node(forms=[_FORM])))
    neg = next(c for c in plan if c.name == "email_required_missing")
    spec = render_e2e_spec(StubAIProvider(), neg, budget_tokens=2048)

    # The oracle provenance is recorded deterministically in the spec header.
    assert "// Generated E2E case: email_required_missing" in spec
    assert "validation_error [email]: rule-derived" in spec
    # The AI-rendered body is included.
    assert "stub-generated by StubAIProvider" in spec


# --- lifecycle integration ---------------------------------------------------


async def test_generate_and_persist_creates_cases_with_provenance(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    page = await _seed_page(db_session, project_id, "/orders", [_FORM])
    generator = E2EGenerator(
        provider=StubAIProvider(), budget_tokens=2048, generated_by="stub"
    )

    results = await generator.generate_and_persist(
        session=db_session, project_id=project_id, page_node_id=page.id
    )

    assert {r.plan.name for r in results} == {"happy", "email_required_missing"}
    assert all(r.action == "created" for r in results)
    for result in results:
        case = result.test_case
        assert case.type is TestType.E2E
        assert case.layer is TestLayer.UI
        assert case.origin is CaseOrigin.GENERATED
        assert case.edited_by_human is False
        assert case.target_node == page.id  # the page node it drives
        assert case.case_key == e2e_case_key("/orders", result.plan.name)
        assert result.test_script.framework.value == "playwright"
        assert result.test_script.deterministic is False


async def test_regen_over_human_edit_yields_proposal_not_clobber(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    page = await _seed_page(db_session, project_id, "/orders", [_FORM])
    generator = E2EGenerator(
        provider=StubAIProvider(), budget_tokens=2048, generated_by="stub"
    )
    first = await generator.generate_and_persist(
        session=db_session, project_id=project_id, page_node_id=page.id
    )
    happy = next(r for r in first if r.plan.name == "happy")

    # A human edits the generated happy case.
    edited = await TestCaseService(db_session).edit(
        project_id, happy.test_case.lineage_id, {"status": "active"}, edited_by="alice"
    )
    assert edited.edited_by_human is True

    # Re-generation lands as a proposal, never overwriting the human edit.
    second = await generator.generate_and_persist(
        session=db_session, project_id=project_id, page_node_id=page.id
    )
    happy2 = next(r for r in second if r.plan.name == "happy")
    assert happy2.action == "proposed"
    assert happy2.test_case.is_current is False
    assert edited.is_current is True  # the human version stays current
