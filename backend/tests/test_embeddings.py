"""Brain embeddings (T2.3) — document builder, embed-on-ingest, semantic search.

Fast lane: the deterministic StubEmbeddingProvider (NO model download). pgvector
itself is real (the test DB), so the HNSW/cosine search SQL is exercised for
real — only the embedding provider is stubbed.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.search import BrainSearch
from app.embeddings.document import build_node_document
from app.embeddings.errors import EmbeddingDimMismatch
from app.embeddings.stub import StubEmbeddingProvider
from app.ingestion.commands import CommandResult
from app.ingestion.laravel.ingester import LaravelIngester
from app.models.enums import NodeKind
from app.models.model_node import EMBEDDING_DIM
from app.repositories.node_repository import NodeRepository
from tests.factories import make_project

# Ingestion is STATIC (ADR-0055): the brain is built from the real Laravel fixture's
# source. A CommandRunner that RAISES proves no app/subprocess boot; source_sha
# bypasses the (optional) git HEAD call.
_FIXTURE = str(Path(__file__).parent / "fixtures" / "laravel-app")
_SHA = "a" * 40


def _no_subprocess(
    argv: Sequence[str], cwd: str | None, timeout: float
) -> CommandResult:
    raise AssertionError(f"ingestion shelled out — must read source only: {list(argv)}")


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


def test_node_document_builder_is_descriptive() -> None:
    endpoint = build_node_document(
        NodeKind.ENDPOINT,
        "POST checkout/discount",
        {
            "method": "POST",
            "uri": "checkout/discount",
            "name": "checkout.discount",
            "action": "App\\Http\\Controllers\\DiscountController@apply",
            "auth_required": True,
            "validation": {"source": "form_request", "fields": ["code", "cart_id"]},
        },
    )
    assert endpoint.startswith("endpoint POST checkout/discount")
    assert "name=checkout.discount" in endpoint
    assert "controller=App\\Http\\Controllers\\DiscountController@apply" in endpoint
    assert "fields=code,cart_id" in endpoint

    model = build_node_document(
        NodeKind.MODEL,
        "App\\Models\\User",
        {"table": "users", "fillable": ["name", "email"], "relationships": []},
    )
    assert model == "model App\\Models\\User table=users fillable=name,email"

    assert build_node_document(NodeKind.TABLE, "users", {"columns": ["id"]}) == (
        "table users columns=id"
    )
    assert build_node_document(NodeKind.ROLE, "admin", {}) == "role admin"


async def test_ingestion_embeds_every_node_with_correct_dimension(
    db_session: AsyncSession,
) -> None:
    pid = await _project(db_session)
    ingester = LaravelIngester(
        runner=_no_subprocess, embedding_provider=StubEmbeddingProvider(EMBEDDING_DIM)
    )
    await ingester.ingest(
        session=db_session, project_id=pid, repo_path=_FIXTURE, source_sha=_SHA
    )

    nodes = NodeRepository(db_session)
    all_nodes = await nodes.list(pid)
    assert len(all_nodes) == 5  # 1 endpoint + 2 models + 2 tables
    for node in all_nodes:
        assert node.embedding is not None
        assert len(node.embedding) == EMBEDDING_DIM  # matches the column dim


async def test_search_returns_semantically_ranked_project_scoped_nodes(
    db_session: AsyncSession,
) -> None:
    stub = StubEmbeddingProvider(EMBEDDING_DIM)
    project_a = await _project(db_session)
    project_b = await _project(db_session)

    await LaravelIngester(runner=_no_subprocess, embedding_provider=stub).ingest(
        session=db_session, project_id=project_a, repo_path=_FIXTURE, source_sha=_SHA
    )

    nodes = NodeRepository(db_session)
    user = await nodes.get_by_key(project_a, NodeKind.MODEL, "App\\Models\\User")
    assert user is not None

    search = BrainSearch(session=db_session, provider=stub)

    # Querying with a node's own document returns that node first (cosine 0).
    user_doc = build_node_document(user.kind, user.name, user.attributes)
    ranked = await search.search_nodes(project_id=project_a, query_text=user_doc, k=3)
    assert ranked[0].id == user.id
    assert all(n.project_id == project_a for n in ranked)

    # Project B has no embedded nodes → no cross-project hits.
    empty = await search.search_nodes(project_id=project_b, query_text=user_doc, k=5)
    assert empty == []


async def test_ingest_rejects_dimension_mismatch(db_session: AsyncSession) -> None:
    pid = await _project(db_session)
    wrong_dim = LaravelIngester(
        runner=_no_subprocess, embedding_provider=StubEmbeddingProvider(dimension=128)
    )
    with pytest.raises(EmbeddingDimMismatch):
        await wrong_dim.ingest(
            session=db_session, project_id=pid, repo_path=_FIXTURE, source_sha=_SHA
        )
