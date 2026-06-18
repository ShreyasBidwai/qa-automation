"""BrainResolver integration (embed lane, real fastembed) — extends T2.3 round-trip.

Marked ``embed``: ingests the canned repo with REAL embeddings, then a natural
NL query resolves to the right endpoint via the hybrid (vector + lexical) score
and carries its 1-hop subgraph. Closes stub-vs-real drift at the resolver level.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.resolver import BrainResolver
from app.embeddings.fastembed_provider import LocalEmbeddingProvider
from app.ingestion.laravel.ingester import LaravelIngester
from app.models.model_node import EMBEDDING_DIM
from tests.factories import make_project
from tests.test_brain_resolver import _runner

pytestmark = pytest.mark.embed


def _provider() -> LocalEmbeddingProvider:
    return LocalEmbeddingProvider(
        model="BAAI/bge-small-en-v1.5", dimension=EMBEDDING_DIM
    )


async def test_real_nl_query_resolves_endpoint_with_subgraph(
    db_session: AsyncSession,
) -> None:
    provider = _provider()
    project = make_project()
    db_session.add(project)
    await db_session.flush()

    await LaravelIngester(runner=_runner(), embedding_provider=provider).ingest(
        session=db_session, project_id=project.id, repo_path="/repo"
    )

    resolver = BrainResolver(session=db_session, provider=provider)
    resolution = await resolver.resolve(
        project_id=project.id, query_text="apply a discount at checkout", k=3
    )

    assert not resolution.low_confidence
    assert resolution.results[0].node.name == "POST checkout/discount"
    # The resolved endpoint carries its 1-hop model neighbour as generation context.
    neighbours = {n.name for n in resolution.results[0].subgraph.nodes}
    assert "App\\Models\\Discount" in neighbours
