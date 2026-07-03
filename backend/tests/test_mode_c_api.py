"""Mode C (API layer) — NL → resolved endpoint → provenanced API proposals (fast).

The API sibling of test_mode_c: a described API scenario resolves to the endpoint
node and authors that endpoint's contract tests through the SAME backend generator,
persisted as PENDING proposals (never auto-adopted).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.stub import StubAIProvider
from app.api.ports import (
    run_request_from_payload,
    run_request_to_payload,
    to_run_request,
)
from app.api.schemas import ModeCRunRequest
from app.embeddings.stub import StubEmbeddingProvider
from app.models.enums import CaseOrigin, NodeKind, ProposalStatus, RunMode, TestLayer
from app.models.model_node import EMBEDDING_DIM, ModelNode
from app.modes.mode_c_api import ApiProposalError, build_mode_c_api_orchestrator
from app.repositories.node_repository import NodeRepository
from tests.factories import make_node, make_project


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


async def _seed_orders_endpoint(
    session: AsyncSession, project_id: uuid.UUID
) -> ModelNode:
    return await NodeRepository(session).add(
        make_node(
            project_id,
            kind=NodeKind.ENDPOINT,
            name="POST api/orders",
            attributes={
                "method": "POST",
                "uri": "api/orders",
                "auth_required": True,
                "validation": {
                    "fields": [
                        {
                            "name": "quantity",
                            "type": "integer",
                            "required": True,
                            "raw_rules": ["required", "integer"],
                        }
                    ]
                },
            },
        )
    )


async def test_mode_c_api_proposes_endpoint_contract_cases(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    await _seed_orders_endpoint(db_session, project_id)

    orchestrator = build_mode_c_api_orchestrator(
        db_session,
        ai_provider=StubAIProvider(),
        embedding_provider=StubEmbeddingProvider(EMBEDDING_DIM),
    )
    result = await orchestrator.propose(
        project_id=project_id,
        nl="the orders endpoint rejects a request with a missing quantity",
    )

    # NL → intent → resolved ENDPOINT (not a page) → API proposals.
    assert result.endpoint.name == "POST api/orders"
    assert result.cases
    # The deterministic plan authors the happy path AND the required-field negative.
    plan_names = {case.plan.name for case in result.cases}
    assert "happy" in plan_names
    assert any(name.startswith("quantity") for name in plan_names)

    for case in result.cases:
        tc = case.test_case
        assert tc.layer is TestLayer.API  # authored at the API layer
        # Persisted as a pending proposal (never auto-adopted).
        assert tc.origin is CaseOrigin.PROPOSED
        assert tc.proposal_status is ProposalStatus.PENDING
        # Provenance stamped on the existing jsonb, tagged with the layer.
        provenance = tc.preconditions["mode_c"]
        assert provenance["layer"] == "api"
        assert "orders" in provenance["keywords"]


async def test_mode_c_api_raises_when_no_endpoint_resolves(
    db_session: AsyncSession,
) -> None:
    # A project with no endpoint node can't author an API test — a clear error, not a
    # silent empty result (the UI surfaces it so the QA can rephrase or ingest first).
    project_id = await _project(db_session)
    db_session.add(
        make_node(project_id, kind=NodeKind.PAGE, name="/checkout", attributes={})
    )
    await db_session.flush()

    orchestrator = build_mode_c_api_orchestrator(
        db_session,
        ai_provider=StubAIProvider(),
        embedding_provider=StubEmbeddingProvider(EMBEDDING_DIM),
    )
    try:
        await orchestrator.propose(project_id=project_id, nl="check the orders api")
        raise AssertionError("expected ApiProposalError")
    except ApiProposalError:
        pass


def test_mode_c_layer_round_trips_through_request_and_payload() -> None:
    # The chosen authoring layer survives body → RunRequest → durable payload → back.
    body = ModeCRunRequest(mode="mode_c", prompt="orders reject bad qty", layer="api")
    request = to_run_request(body)
    assert request.mode is RunMode.C and request.layer == "api"

    payload = run_request_to_payload(request)
    assert payload["layer"] == "api"
    assert run_request_from_payload(payload).layer == "api"


def test_mode_c_layer_defaults_to_ui() -> None:
    # Omitting the layer keeps the existing UI page-journey behaviour.
    body = ModeCRunRequest(mode="mode_c", prompt="describe the checkout")
    assert body.layer == "ui"
    assert to_run_request(body).layer == "ui"
