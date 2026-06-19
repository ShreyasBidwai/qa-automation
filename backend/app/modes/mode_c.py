"""Mode C orchestrator — natural-language test authoring (T5 core).

Ties the pieces together: NL → TestIntent (AI; nl_intent) → proposed journey
(deterministic; nl_journey) → generated E2E PROPOSALS (e2e_generator via
proposals.py). Records provenance — the originating request, intent, and resolved
page — on each proposed case so a reviewer can see why it exists. Thin by design:
all real work lives in the reused components; this only sequences them and stamps
provenance. Exposed via ``build_mode_c_orchestrator`` for integration to wire
(coordination contract: no DI/router edits here).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.types import AIProvider
from app.embeddings.types import EmbeddingProvider
from app.generation.e2e_generator import E2EGenerator, GeneratedE2ECase
from app.generation.nl_intent import TestIntent, parse_test_intent
from app.generation.nl_journey import JourneyProposal, propose_journey

from .proposals import generate_proposed_cases

logger = logging.getLogger("app.modes.mode_c")

_DEFAULT_GENERATED_BY = "mode-c"
_DEFAULT_BUDGET_TOKENS = 2048


@dataclass(frozen=True)
class ModeCResult:
    """The outcome of one NL authoring request, with full provenance."""

    intent: TestIntent
    proposal: JourneyProposal
    cases: list[GeneratedE2ECase]


def _provenance(nl: str, intent: TestIntent) -> dict[str, Any]:
    return {
        "nl": nl,
        "keywords": list(intent.keywords),
        "scenario_type": intent.scenario_type.value,
    }


class ModeCOrchestrator:
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

    async def propose(self, *, project_id: uuid.UUID, nl: str) -> ModeCResult:
        """NL request → intent → journey → persisted E2E proposals (provenanced)."""
        intent = parse_test_intent(self._ai, nl, budget_tokens=self._budget)
        proposal = await propose_journey(
            session=self._session,
            project_id=project_id,
            intent=intent,
            embedding_provider=self._embed,
        )
        generator = E2EGenerator(
            provider=self._ai,
            budget_tokens=self._budget,
            generated_by=self._generated_by,
        )
        cases = await generate_proposed_cases(
            session=self._session,
            project_id=project_id,
            page_node_id=proposal.page.id,
            generator=generator,
        )

        # Stamp provenance on each proposal (existing jsonb — no new column).
        provenance = _provenance(nl, intent)
        for case in cases:
            tc = case.test_case
            tc.preconditions = {**tc.preconditions, "mode_c": provenance}
        await self._session.flush()

        logger.info(
            "modes.mode_c.proposed",
            extra={
                "project_id": str(project_id),
                "scenario_type": intent.scenario_type.value,
                "page": proposal.page.name,
                "case_count": len(cases),
            },
        )
        return ModeCResult(intent=intent, proposal=proposal, cases=cases)


def build_mode_c_orchestrator(
    session: AsyncSession,
    *,
    ai_provider: AIProvider,
    embedding_provider: EmbeddingProvider,
    generated_by: str = _DEFAULT_GENERATED_BY,
    budget_tokens: int = _DEFAULT_BUDGET_TOKENS,
) -> ModeCOrchestrator:
    """Factory for integration to wire (no composition-root edits here)."""
    return ModeCOrchestrator(
        session=session,
        ai_provider=ai_provider,
        embedding_provider=embedding_provider,
        generated_by=generated_by,
        budget_tokens=budget_tokens,
    )
