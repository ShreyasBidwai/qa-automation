"""Mode C step 2 — TestIntent → proposed journey (fast; seeded Brain nodes)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings.stub import StubEmbeddingProvider
from app.generation.nl_intent import ScenarioType, TestIntent
from app.generation.nl_journey import JourneyProposalError, propose_journey
from app.models.enums import EdgeKind, NodeKind
from app.models.model_node import EMBEDDING_DIM, ModelNode
from app.repositories.edge_repository import EdgeRepository
from app.repositories.node_repository import NodeRepository
from tests.factories import make_edge, make_node, make_project


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


async def _node(
    session: AsyncSession,
    project_id: uuid.UUID,
    kind: NodeKind,
    name: str,
    **attributes: object,
) -> ModelNode:
    return await NodeRepository(session).add(
        make_node(project_id, kind=kind, name=name, attributes=dict(attributes))
    )


def _intent(
    *keywords: str, scenario: ScenarioType = ScenarioType.JOURNEY
) -> TestIntent:
    return TestIntent(
        raw_nl=" ".join(keywords), keywords=keywords, scenario_type=scenario
    )


async def test_propose_journey_resolves_intent_to_page(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    page = await _node(
        db_session,
        project_id,
        NodeKind.PAGE,
        "/checkout",
        path="/checkout",
        title="Checkout",
    )
    endpoint = await _node(
        db_session,
        project_id,
        NodeKind.ENDPOINT,
        "POST api/checkout",
        method="POST",
        uri="api/checkout",
    )
    await EdgeRepository(db_session).add(
        make_edge(project_id, page.id, endpoint.id, kind=EdgeKind.CALLS)
    )

    proposal = await propose_journey(
        session=db_session,
        project_id=project_id,
        intent=_intent("checkout"),
        embedding_provider=StubEmbeddingProvider(EMBEDDING_DIM),
    )

    assert proposal.page.kind is NodeKind.PAGE
    assert proposal.page.name == "/checkout"
    names = {n.name for n in proposal.journey.nodes}
    assert {"/checkout", "POST api/checkout"} <= names  # cross-layer journey


async def test_propose_journey_without_a_page_raises(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    # Only an endpoint resolves — no page to start a journey from.
    await _node(
        db_session,
        project_id,
        NodeKind.ENDPOINT,
        "GET api/orders",
        method="GET",
        uri="api/orders",
    )
    with pytest.raises(JourneyProposalError):
        await propose_journey(
            session=db_session,
            project_id=project_id,
            intent=_intent("orders"),
            embedding_provider=StubEmbeddingProvider(EMBEDDING_DIM),
        )
