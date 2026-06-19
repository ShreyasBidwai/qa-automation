"""Mode C step 3 — generate cases as pending proposals; never clobber (fast)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.stub import StubAIProvider
from app.generation.e2e_generator import E2EGenerator
from app.models.enums import CaseOrigin, NodeKind, ProposalStatus
from app.models.model_node import ModelNode
from app.modes.proposals import generate_proposed_cases
from app.repositories.node_repository import NodeRepository
from app.services.test_case_service import TestCaseService
from tests.factories import make_node, make_project

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


async def _seed_page(session: AsyncSession, project_id: uuid.UUID) -> ModelNode:
    return await NodeRepository(session).add(
        make_node(
            project_id,
            kind=NodeKind.PAGE,
            name="/checkout",
            attributes={"path": "/checkout", "title": "Checkout", "forms": [_FORM]},
        )
    )


def _generator() -> E2EGenerator:
    return E2EGenerator(
        provider=StubAIProvider(), budget_tokens=2048, generated_by="mode-c"
    )


async def test_generated_cases_are_pending_proposals(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    page = await _seed_page(db_session, project_id)

    results = await generate_proposed_cases(
        session=db_session,
        project_id=project_id,
        page_node_id=page.id,
        generator=_generator(),
    )

    assert {r.plan.name for r in results} == {"happy", "email_required_missing"}
    for result in results:
        assert result.test_case.origin is CaseOrigin.PROPOSED
        assert result.test_case.proposal_status is ProposalStatus.PENDING


async def test_regen_over_human_edit_never_clobbers(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    page = await _seed_page(db_session, project_id)

    first = await generate_proposed_cases(
        session=db_session,
        project_id=project_id,
        page_node_id=page.id,
        generator=_generator(),
    )
    happy = next(r for r in first if r.plan.name == "happy")

    # A human takes the proposal and edits it.
    edited = await TestCaseService(db_session).edit(
        project_id, happy.test_case.lineage_id, {"status": "active"}, edited_by="alice"
    )
    assert edited.edited_by_human is True

    # Re-running Mode C proposes against the human edit — never overwrites it.
    second = await generate_proposed_cases(
        session=db_session,
        project_id=project_id,
        page_node_id=page.id,
        generator=_generator(),
    )
    happy2 = next(r for r in second if r.plan.name == "happy")
    assert happy2.action == "proposed"
    assert happy2.test_case.is_current is False
    assert edited.is_current is True  # the human version stays current, untouched
