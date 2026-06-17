"""Real-embedding integration (T2.3) — closes stub-vs-real drift.

Marked ``embed``: runs ONLY in the embed lane (`make test-embeddings`), where
fastembed is installed. Verifies the real provider returns 384-dim vectors and
that an insert + pgvector cosine search round-trip returns the nearest node —
the same drift-closing pattern as the php-parser shape tests.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.search import BrainSearch
from app.embeddings.fastembed_provider import LocalEmbeddingProvider
from app.models.enums import NodeKind
from app.models.model_node import EMBEDDING_DIM, ModelNode
from app.repositories.node_repository import NodeRepository
from tests.factories import make_node, make_project

pytestmark = pytest.mark.embed


def _provider() -> LocalEmbeddingProvider:
    return LocalEmbeddingProvider(
        model="BAAI/bge-small-en-v1.5", dimension=EMBEDDING_DIM
    )


def test_real_provider_returns_correct_dimension() -> None:
    vectors = _provider().embed(["a checkout discount endpoint", "the user model"])
    assert len(vectors) == 2
    assert all(len(v) == EMBEDDING_DIM for v in vectors)


async def test_insert_and_search_roundtrip_returns_nearest(
    db_session: AsyncSession,
) -> None:
    provider = _provider()
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    pid: uuid.UUID = project.id

    nodes = NodeRepository(db_session)
    discount_doc = "endpoint POST checkout/discount controller=DiscountController@apply"
    user_doc = "model App\\Models\\User table=users fillable=name,email"
    discount = await nodes.add(
        make_node(
            pid,
            kind=NodeKind.ENDPOINT,
            name="POST checkout/discount",
            embedding=provider.embed([discount_doc])[0],
        )
    )
    await nodes.add(
        make_node(
            pid,
            kind=NodeKind.MODEL,
            name="App\\Models\\User",
            embedding=provider.embed([user_doc])[0],
        )
    )

    search = BrainSearch(session=db_session, provider=provider)
    ranked = await search.search_nodes(
        project_id=pid, query_text="apply a discount code at checkout", k=1
    )
    assert len(ranked) == 1
    assert ranked[0].id == discount.id


def test_factory_builds_local_provider_from_config() -> None:
    from app.core.config import Settings

    settings = Settings(  # type: ignore[call-arg]
        database_url="postgresql+psycopg://x:y@db:5432/z",
        embedding_provider="local",
    )
    from app.embeddings.factory import build_embedding_provider

    provider = build_embedding_provider(settings)
    assert provider.dimension == EMBEDDING_DIM
    assert isinstance(provider, LocalEmbeddingProvider)
