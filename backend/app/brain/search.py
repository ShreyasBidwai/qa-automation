"""BrainSearch — basic NL → node semantic search (T2.3).

Embeds the query with the configured EmbeddingProvider and returns the top-k
nearest nodes by cosine similarity via the HNSW-indexed pgvector column,
project-scoped. The richer BrainResolver (codebase fallback, graph expansion,
re-ranking) is T2.4; this is deliberately just the core vector search.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings.types import EmbeddingProvider
from app.models.model_node import ModelNode
from app.repositories.node_repository import NodeRepository


class BrainSearch:
    def __init__(self, *, session: AsyncSession, provider: EmbeddingProvider) -> None:
        self._session = session
        self._provider = provider

    async def search_nodes(
        self, *, project_id: uuid.UUID, query_text: str, k: int = 5
    ) -> list[ModelNode]:
        query_vector = self._provider.embed([query_text])[0]
        return await NodeRepository(self._session).search_by_vector(
            project_id, query_vector, k
        )
