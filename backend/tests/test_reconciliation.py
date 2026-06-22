"""Spec-vs-code reconciliation (B9, ADR-0039) — concrete, false-positive-guarded.

Flags a doc that references a CONCRETE endpoint the code Brain lacks; does NOT flag
fuzzy prose; does NOT flag when there is no code model to reconcile against.
Deterministic, no AI.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.reconcile import extract_route_references, reconcile_document
from app.models.enums import NodeKind
from app.models.project_document import ProjectDocument
from app.repositories.node_repository import NodeRepository
from app.repositories.spec_divergence_repository import SpecDivergenceRepository
from tests.factories import make_node, make_project


async def _project_with_endpoint(db_session: AsyncSession) -> uuid.UUID:
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    # The code Brain knows POST /users (and nothing else).
    await NodeRepository(db_session).add(
        make_node(
            project.id,
            kind=NodeKind.ENDPOINT,
            name="POST users",
            attributes={"method": "POST", "uri": "users"},
        )
    )
    return project.id


async def _doc(db_session: AsyncSession, project_id: uuid.UUID, content: str):  # type: ignore[no-untyped-def]
    document = ProjectDocument(
        project_id=project_id,
        title="API contract",
        doc_kind="api_contract",
        content=content,
        content_sha="sha",
    )
    db_session.add(document)
    await db_session.flush()
    return document


# --- the concrete-reference extractor (pure) ---------------------------------


def test_extract_route_references_is_concrete_only() -> None:
    refs = extract_route_references(
        "The API exposes POST /users and GET /orders/{id}. "
        "Customers can post their widgets to the queue."  # prose — must NOT match
    )
    pairs = {(m, p) for m, p, _ in refs}
    assert ("POST", "users") in pairs
    assert ("GET", "orders/{id}") in pairs
    assert all(m in {"GET", "POST", "PUT", "PATCH", "DELETE"} for m, _, _ in refs)
    assert len(pairs) == 2  # the prose "post their widgets" is not a route ref


# --- reconciliation ----------------------------------------------------------


async def test_flags_a_missing_endpoint(db_session: AsyncSession) -> None:
    project_id = await _project_with_endpoint(db_session)
    document = await _doc(
        db_session,
        project_id,
        "The API exposes POST /users and POST /widgets for partner integrations.",
    )

    divergences = await reconcile_document(
        db_session, project_id=project_id, document=document
    )
    # POST /users exists in the Brain → not flagged; POST /widgets is missing → flagged.
    assert len(divergences) == 1
    div = divergences[0]
    assert div.kind == "endpoint_missing"
    assert div.spec_reference == "POST /widgets"
    assert "no matching endpoint" in div.code_observation
    assert div.confidence == "high"

    stored = await SpecDivergenceRepository(db_session).list(project_id)
    assert len(stored) == 1 and stored[0].spec_reference == "POST /widgets"


async def test_does_not_flag_fuzzy_prose(db_session: AsyncSession) -> None:
    project_id = await _project_with_endpoint(db_session)
    document = await _doc(
        db_session,
        project_id,
        "Users should be able to check out quickly and manage their widgets and "
        "discount codes from the account page.",  # no concrete METHOD /path
    )
    divergences = await reconcile_document(
        db_session, project_id=project_id, document=document
    )
    assert divergences == []


async def test_does_not_flag_existing_endpoint(db_session: AsyncSession) -> None:
    project_id = await _project_with_endpoint(db_session)
    document = await _doc(db_session, project_id, "Create a user via POST /users.")
    divergences = await reconcile_document(
        db_session, project_id=project_id, document=document
    )
    assert divergences == []


async def test_skips_when_no_code_model(db_session: AsyncSession) -> None:
    project = make_project()  # NO endpoint nodes ingested
    db_session.add(project)
    await db_session.flush()
    document = await _doc(
        db_session, project.id, "The API exposes POST /widgets and GET /things."
    )
    # No code endpoints → can't honestly say "code lacks X" → flag nothing.
    divergences = await reconcile_document(
        db_session, project_id=project.id, document=document
    )
    assert divergences == []
