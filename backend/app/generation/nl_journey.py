"""Mode C, step 2 — resolve a TestIntent into a proposed journey (T5 core).

Deterministic: the only AI was producing the intent (step 1). Here the intent's
keywords are resolved against the Brain (BrainResolver — vector + lexical, with a
deterministic lexical fallback) to pick the page the journey starts at, then the
T4.3 CrossLayerResolver expands the cross-layer journey subgraph (page → endpoint
→ table). Project-scoped. New ``nl_*`` file; reuses the shared resolvers as-is.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.cross_layer import CrossLayerResolver, Subgraph
from app.brain.resolver import BrainResolver
from app.embeddings.types import EmbeddingProvider
from app.models.enums import NodeKind
from app.models.model_node import ModelNode

from .errors import GenerationError
from .nl_intent import TestIntent


class JourneyProposalError(GenerationError):
    """The intent did not resolve to a page to start a journey from."""


@dataclass(frozen=True)
class JourneyProposal:
    intent: TestIntent
    page: ModelNode  # the resolved journey start (a page node)
    journey: Subgraph  # the cross-layer journey subgraph from CrossLayerResolver
    confidence: float  # the resolver's blended score for the chosen page


async def propose_journey(
    *,
    session: AsyncSession,
    project_id: uuid.UUID,
    intent: TestIntent,
    embedding_provider: EmbeddingProvider,
    k: int = 5,
) -> JourneyProposal:
    """Resolve ``intent`` to a page and expand its cross-layer journey."""
    resolver = BrainResolver(session=session, provider=embedding_provider)
    resolution = await resolver.resolve(
        project_id=project_id, query_text=" ".join(intent.keywords), k=k
    )

    # A Mode-C journey starts at a page; take the highest-ranked page result.
    page_result = next(
        (r for r in resolution.results if r.node.kind is NodeKind.PAGE), None
    )
    if page_result is None:
        raise JourneyProposalError(
            f"no page resolved for intent keywords {list(intent.keywords)}"
        )

    journey = await CrossLayerResolver(session).journey(project_id, page_result.node.id)
    return JourneyProposal(
        intent=intent,
        page=page_result.node,
        journey=journey,
        confidence=page_result.score,
    )
