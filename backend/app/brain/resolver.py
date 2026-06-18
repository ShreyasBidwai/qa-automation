"""BrainResolver — hybrid NL → ranked, context-bearing nodes (T2.4).

The piece Mode C's prompt path calls. It blends two signals into one score per
node: vector similarity (T2.3 cosine ANN) and a deterministic lexical signal
(query tokens vs the node's document). Codebase facts are ground truth and the
Brain is a derived accelerator, so resolution NEVER depends solely on embeddings:
when vectors are weak/absent (or embedding fails) it falls back to pure lexical
matching over the ingested nodes. Each top result is expanded with its bounded
1-hop neighbours into a ``Subgraph`` (the same context type the T1.4 generator
consumes). Project-scoped throughout.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.types import Subgraph, SubgraphEdge, SubgraphNode
from app.embeddings.errors import EmbeddingError
from app.embeddings.types import EmbeddingProvider
from app.models.model_node import ModelNode
from app.repositories.edge_repository import EdgeRepository
from app.repositories.node_repository import NodeRepository

from .lexical import lexical_score

logger = logging.getLogger("app.brain")

# Defaults mirror the config (Settings.resolver_*); injectable for testing.
DEFAULT_VECTOR_WEIGHT = 0.6
DEFAULT_LEXICAL_WEIGHT = 0.4
DEFAULT_VECTOR_MIN_SIMILARITY = 0.15
DEFAULT_CONFIDENCE_THRESHOLD = 0.35
DEFAULT_VECTOR_CANDIDATES = 20
DEFAULT_SUBGRAPH_MAX_NEIGHBORS = 10


@dataclass(frozen=True)
class ResolvedNode:
    node: ModelNode
    score: float  # blended confidence in [0, 1]
    subgraph: Subgraph  # the node + its bounded 1-hop neighbours (generation context)


@dataclass(frozen=True)
class Resolution:
    query: str
    results: list[ResolvedNode]
    # True when the top result is below the confidence threshold (or nothing
    # resolved) — the caller (Mode C) should disambiguate rather than guess.
    low_confidence: bool


def _to_subgraph_node(node: ModelNode) -> SubgraphNode:
    return SubgraphNode(
        id=str(node.id),
        kind=node.kind.value,
        name=node.name,
        attributes=node.attributes,
        source_sha=node.source_sha,
    )


class BrainResolver:
    def __init__(
        self,
        *,
        session: AsyncSession,
        provider: EmbeddingProvider,
        vector_weight: float = DEFAULT_VECTOR_WEIGHT,
        lexical_weight: float = DEFAULT_LEXICAL_WEIGHT,
        vector_min_similarity: float = DEFAULT_VECTOR_MIN_SIMILARITY,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        vector_candidates: int = DEFAULT_VECTOR_CANDIDATES,
        subgraph_max_neighbors: int = DEFAULT_SUBGRAPH_MAX_NEIGHBORS,
    ) -> None:
        self._session = session
        self._provider = provider
        self._w_vec = vector_weight
        self._w_lex = lexical_weight
        self._vector_min_similarity = vector_min_similarity
        self._confidence_threshold = confidence_threshold
        self._vector_candidates = vector_candidates
        self._subgraph_max_neighbors = subgraph_max_neighbors

    async def resolve(
        self, *, project_id: uuid.UUID, query_text: str, k: int = 5
    ) -> Resolution:
        nodes = NodeRepository(self._session)
        edges = EdgeRepository(self._session)

        candidates = await nodes.list(project_id)
        if not candidates:
            return Resolution(query=query_text, results=[], low_confidence=True)

        vector_sims = await self._vector_sims(nodes, project_id, query_text)
        # Vectors are only trusted when the best similarity clears the floor;
        # otherwise (weak or absent) resolution is pure lexical — the codebase
        # facts are ground truth, never dependent on embedding freshness.
        # (A deeper fallback — re-scanning live code — is a later task.)
        vectors_usable = bool(vector_sims) and (
            max(vector_sims.values()) >= self._vector_min_similarity
        )

        scored: list[tuple[ModelNode, float]] = []
        for node in candidates:
            lexical = lexical_score(query_text, node)
            if vectors_usable:
                score = self._w_vec * vector_sims.get(node.id, 0.0) + (
                    self._w_lex * lexical
                )
            else:
                score = lexical
            scored.append((node, score))

        # Deterministic ordering: score desc, then name for stable ties.
        scored.sort(key=lambda item: (-item[1], item[0].name))
        top = scored[:k]

        results = [
            ResolvedNode(
                node=node,
                score=score,
                subgraph=await self._subgraph(nodes, edges, project_id, node),
            )
            for node, score in top
        ]
        low_confidence = not results or results[0].score < self._confidence_threshold
        logger.info(
            "brain.resolver.resolved",
            extra={
                "query": query_text,
                "results": len(results),
                "top_score": results[0].score if results else 0.0,
                "vectors_usable": vectors_usable,
                "low_confidence": low_confidence,
            },
        )
        return Resolution(
            query=query_text, results=results, low_confidence=low_confidence
        )

    async def _vector_sims(
        self, nodes: NodeRepository, project_id: uuid.UUID, query_text: str
    ) -> dict[uuid.UUID, float]:
        """node_id → cosine similarity (vector top-N); {} if weak/absent/failed."""
        try:
            query_vector = self._provider.embed([query_text])[0]
        except EmbeddingError:
            # Ground-truth guarantee: an embedding outage never blocks resolution.
            logger.warning("brain.resolver.embedding_failed_lexical_fallback")
            return {}
        scored = await nodes.search_by_vector_scored(
            project_id, query_vector, self._vector_candidates
        )
        # pgvector <=> is cosine distance (0=identical); similarity = 1 - distance.
        return {node.id: max(0.0, 1.0 - distance) for node, distance in scored}

    async def _subgraph(
        self,
        nodes: NodeRepository,
        edges: EdgeRepository,
        project_id: uuid.UUID,
        center: ModelNode,
    ) -> Subgraph:
        incident = await edges.list_incident(
            project_id, center.id, self._subgraph_max_neighbors
        )
        neighbor_ids = {e.src_node_id for e in incident} | {
            e.dst_node_id for e in incident
        }
        neighbor_ids.discard(center.id)
        neighbors = await nodes.get_many(project_id, neighbor_ids)
        sg_nodes = [_to_subgraph_node(center)] + [
            _to_subgraph_node(n) for n in neighbors
        ]
        sg_edges = [
            SubgraphEdge(
                src=str(e.src_node_id), dst=str(e.dst_node_id), kind=e.kind.value
            )
            for e in incident
        ]
        return Subgraph(nodes=sg_nodes, edges=sg_edges)
