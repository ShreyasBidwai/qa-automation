"""Mode C orchestrator — NL → intent → journey → provenanced proposals (fast)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.stub import StubAIProvider
from app.embeddings.stub import StubEmbeddingProvider
from app.generation.nl_intent import ScenarioType
from app.models.enums import CaseOrigin, NodeKind, ProposalStatus
from app.models.model_node import EMBEDDING_DIM, ModelNode
from app.modes.mode_c import build_mode_c_orchestrator
from app.repositories.node_repository import NodeRepository
from tests.factories import make_node, make_project

_ORACLE_TIERS = {"rule-derived", "characterization", "spec-grounded"}
_FORM = {
    "action": "/api/checkout",
    "method": "POST",
    "fields": [{"name": "email", "type": "email", "required": True}],
}


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


async def _seed_checkout_page(
    session: AsyncSession, project_id: uuid.UUID
) -> ModelNode:
    return await NodeRepository(session).add(
        make_node(
            project_id,
            kind=NodeKind.PAGE,
            name="/checkout",
            attributes={"path": "/checkout", "title": "Checkout", "forms": [_FORM]},
        )
    )


async def test_mode_c_proposes_provenanced_oracle_honest_cases(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    await _seed_checkout_page(db_session, project_id)

    orchestrator = build_mode_c_orchestrator(
        db_session,
        ai_provider=StubAIProvider(),
        embedding_provider=StubEmbeddingProvider(EMBEDDING_DIM),
    )
    result = await orchestrator.propose(
        project_id=project_id, nl="test the checkout flow"
    )

    # NL → intent (the one AI edge) → resolved journey → proposals.
    assert result.intent.scenario_type is ScenarioType.JOURNEY
    assert "checkout" in result.intent.keywords
    assert result.proposal.page.name == "/checkout"
    assert result.cases

    for case in result.cases:
        tc = case.test_case
        # Persisted as a pending proposal (never auto-adopted).
        assert tc.origin is CaseOrigin.PROPOSED
        assert tc.proposal_status is ProposalStatus.PENDING
        # Provenance stamped on the existing jsonb (no new column).
        assert tc.preconditions["mode_c"]["nl"] == "test the checkout flow"
        assert "checkout" in tc.preconditions["mode_c"]["keywords"]
        # Oracle honesty preserved end-to-end: every assertion is tagged.
        assertions = tc.expected["assertions"]
        assert assertions
        for assertion in assertions:
            assert assertion["oracle_source"] in _ORACLE_TIERS
