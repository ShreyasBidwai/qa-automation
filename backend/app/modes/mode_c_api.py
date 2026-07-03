"""Mode C — the API layer: NL → the endpoint it describes → PROPOSED API tests.

The sibling of ``mode_c.py`` (the UI page-journey path). Where the UI path resolves
an intent to a PAGE and composes a browser journey, this resolves it to the best
ENDPOINT node and runs the SAME deterministic-plan + AI-render generator mode_b uses
for that one endpoint — so the API tests are grounded in the endpoint's real contract
(never invented) and land as proposals a human accepts.

Reuses, unchanged: ``parse_test_intent`` (NL → intent), ``BrainResolver`` (intent →
ranked nodes), ``endpoint_spec_from_node`` (Brain node → EndpointSpec), the backend
``TestGenerator``, and ``generate_proposed_api_cases`` (persist + re-tag PROPOSED).
See ADR-0059 for the design (why reuse the endpoint generator, the review gate).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.types import AIProvider
from app.brain.resolver import BrainResolver
from app.embeddings.types import EmbeddingProvider
from app.generation.endpoint_from_node import endpoint_spec_from_node
from app.generation.generator import GeneratedCase, TestGenerator
from app.generation.nl_intent import TestIntent, parse_test_intent
from app.models.enums import NodeKind
from app.models.model_node import ModelNode

from .proposals import generate_proposed_api_cases

logger = logging.getLogger("app.modes.mode_c_api")

_DEFAULT_GENERATED_BY = "mode-c-api"
_DEFAULT_BUDGET_TOKENS = 2048
# How many ranked candidates to scan for an endpoint before giving up.
_RESOLVE_K = 8


class ApiProposalError(Exception):
    """The description did not resolve to an endpoint to author API tests for."""


@dataclass(frozen=True)
class ModeCApiResult:
    intent: TestIntent
    endpoint: ModelNode  # the resolved endpoint the cases target
    cases: list[GeneratedCase]
    confidence: float


def _provenance(nl: str, intent: TestIntent) -> dict[str, Any]:
    return {
        "nl": nl,
        "keywords": list(intent.keywords),
        "scenario_type": intent.scenario_type.value,
        "layer": "api",
    }


class ModeCApiOrchestrator:
    def __init__(
        self,
        *,
        session: AsyncSession,
        ai_provider: AIProvider,
        embedding_provider: EmbeddingProvider,
        generated_by: str = _DEFAULT_GENERATED_BY,
        budget_tokens: int = _DEFAULT_BUDGET_TOKENS,
    ) -> None:
        self._session = session
        self._ai = ai_provider
        self._embed = embedding_provider
        self._generated_by = generated_by
        self._budget = budget_tokens

    async def propose(self, *, project_id: uuid.UUID, nl: str) -> ModeCApiResult:
        """NL → intent → resolved endpoint → persisted API proposals (provenanced)."""
        intent = parse_test_intent(self._ai, nl, budget_tokens=self._budget)
        resolver = BrainResolver(session=self._session, provider=self._embed)
        resolution = await resolver.resolve(
            project_id=project_id,
            query_text=" ".join(intent.keywords),
            k=_RESOLVE_K,
        )
        # An API mode-C run targets an endpoint; take the highest-ranked endpoint node.
        endpoint = next(
            (r for r in resolution.results if r.node.kind is NodeKind.ENDPOINT), None
        )
        if endpoint is None:
            raise ApiProposalError(
                f"no endpoint resolved for description keywords {list(intent.keywords)}"
            )

        spec = endpoint_spec_from_node(endpoint.node)
        generator = TestGenerator(
            provider=self._ai,
            budget_tokens=self._budget,
            generated_by=self._generated_by,
        )
        cases = await generate_proposed_api_cases(
            session=self._session,
            project_id=project_id,
            spec=spec,
            generator=generator,
        )

        # Stamp provenance on each proposal (existing jsonb — no new column).
        provenance = _provenance(nl, intent)
        for case in cases:
            tc = case.test_case
            tc.preconditions = {**tc.preconditions, "mode_c": provenance}
        await self._session.flush()

        logger.info(
            "modes.mode_c_api.proposed",
            extra={
                "project_id": str(project_id),
                "scenario_type": intent.scenario_type.value,
                "endpoint": endpoint.node.name,
                "case_count": len(cases),
            },
        )
        return ModeCApiResult(
            intent=intent,
            endpoint=endpoint.node,
            cases=cases,
            confidence=endpoint.score,
        )


def build_mode_c_api_orchestrator(
    session: AsyncSession,
    *,
    ai_provider: AIProvider,
    embedding_provider: EmbeddingProvider,
    generated_by: str = _DEFAULT_GENERATED_BY,
    budget_tokens: int = _DEFAULT_BUDGET_TOKENS,
) -> ModeCApiOrchestrator:
    """Factory for the API-layer authoring orchestrator (mirrors mode_c's factory)."""
    return ModeCApiOrchestrator(
        session=session,
        ai_provider=ai_provider,
        embedding_provider=embedding_provider,
        generated_by=generated_by,
        budget_tokens=budget_tokens,
    )
