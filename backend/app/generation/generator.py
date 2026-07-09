"""TestGenerator — orchestrates plan → render → merge-persist (Standards §5).

Planning is fully deterministic; the AIProvider only renders. Persistence of
cases goes through the CaseMergeService so re-running generation is
idempotent-by-key and never clobbers a human edit (T3.2): cases are reconciled
against existing lineages by their deterministic ``case_key``, and each rendered
script is attached to whichever case version the merge produced. Does NOT execute
the tests (that is T1.5).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.types import AIProvider
from app.ingestion.models import EndpointSpec
from app.models.enums import AuthoredBy, CaseOrigin, Framework, TestLayer
from app.models.test_case import TestCase
from app.models.test_script import TestScript
from app.repositories.generation_signal_repository import GenerationSignalRepository
from app.repositories.test_script_repository import TestScriptRepository
from app.services.case_merge_service import CaseMergeService, MergeAction

from .case_key import compute_case_key
from .plan import PlannedCase, plan_cases
from .render import render_script
from .version import PROMPT_VERSION

if TYPE_CHECKING:
    from app.documents.grounding import SpecGroundingService

logger = logging.getLogger("app.generation")


@dataclass
class GeneratedCase:
    plan: PlannedCase
    test_case: TestCase
    test_script: TestScript
    action: MergeAction  # how the merge engine reconciled this case


def _to_test_case(
    project_id: uuid.UUID, spec: EndpointSpec, case: PlannedCase, case_key: str
) -> TestCase:
    return TestCase(
        project_id=project_id,
        type=case.case_type,
        layer=TestLayer.API,
        # FK to model_nodes not available yet; endpoint identity lives in preconditions.
        target_node=None,
        preconditions={
            "endpoint": {
                "method": spec.method,
                "uri": spec.uri,
                "route_name": spec.route_name,
            },
            "auth_required": spec.auth_required,
            "db_dependencies": [asdict(dep) for dep in case.dependencies],
        },
        steps={
            "method": spec.method,
            "uri": spec.uri,
            "path_values": case.path_values,
            "authenticated": case.authenticated,
            "payload": case.payload,
            "case": case.name,
            "rule": case.rule,
        },
        expected={"status": case.expected.status, "shape": case.expected.shape},
        oracle_source=case.oracle_source,
        authored_by=AuthoredBy.AI,
        edited_by_human=False,
        origin=CaseOrigin.GENERATED,
        case_key=case_key,
        gen_prompt_version=PROMPT_VERSION,  # flywheel attribution (ADR-0070)
        gen_strategy="endpoint",
    )


def _to_test_script(
    project_id: uuid.UUID, test_case_id: uuid.UUID, code: str, generated_by: str
) -> TestScript:
    return TestScript(
        project_id=project_id,
        test_case_id=test_case_id,
        framework=Framework.PEST,
        code=code,
        generated_by=generated_by,
        deterministic=False,
    )


class TestGenerator:
    def __init__(
        self,
        *,
        provider: AIProvider,
        budget_tokens: int,
        generated_by: str,
        factories_available: bool = True,
        grounder: SpecGroundingService | None = None,
    ) -> None:
        self._provider = provider
        self._budget = budget_tokens
        self._generated_by = generated_by
        # Whether the target defines model factories (ADR-0037); drives render_script
        # off factory-dependent setup when it doesn't.
        self._factories_available = factories_available
        # Optional spec-grounding (B9): upgrades doc-backed cases to spec-grounded.
        self._grounder = grounder

    def plan(self, spec: EndpointSpec) -> list[PlannedCase]:
        """PHASE 1 — pure, deterministic, AI-free."""
        return plan_cases(spec)

    async def generate_and_persist(
        self, *, session: AsyncSession, project_id: uuid.UUID, spec: EndpointSpec
    ) -> list[GeneratedCase]:
        cases = self.plan(spec)
        # Spec-grounding (B9): upgrade doc-backed cases to spec-grounded BEFORE
        # render, so the renderer sees the upgraded oracle stance (case_key is
        # unaffected — it doesn't key on oracle_source).
        if self._grounder is not None:
            cases = await self._grounder.ground(
                project_id=project_id, spec=spec, cases=cases
            )
        merge = CaseMergeService(session)
        script_repo = TestScriptRepository(session)

        # Retrieval (Loop 1, ADR-0070): this project's own previously-passing tests for
        # the same route class, fed to the renderer as few-shot so each run sharpens the
        # next. Best-effort — empty on a cold start, and never blocks generation.
        try:
            exemplars = await GenerationSignalRepository(session).good_exemplars(
                project_id, "api" if spec.is_api else "web"
            )
        except Exception:  # noqa: BLE001 — retrieval is an optimization, never fatal
            exemplars = []

        # Render every case, then reconcile the whole set through the merge engine
        # (create / update / propose) — never a blind write; human-edited cases
        # are protected. Scripts attach to whichever version the merge produced.
        # Render the cases CONCURRENTLY: each `render_script` is a blocking, sync
        # AI call (via the bridge), so run them off the event loop in threads and
        # await them together. render_script is pure (no DB/session) and the usage
        # collector's append is atomic under the GIL, so this is race-free; the AI
        # calls fan out (bounded downstream by the bridge's own concurrency gate),
        # while all DB work below stays on the one session, serial. Order preserved.
        codes = list(
            await asyncio.gather(
                *(
                    asyncio.to_thread(
                        render_script,
                        self._provider,
                        spec,
                        c,
                        self._budget,
                        factories_available=self._factories_available,
                        exemplars=exemplars,
                    )
                    for c in cases
                )
            )
        )
        candidates = [
            _to_test_case(project_id, spec, c, compute_case_key(spec, c)) for c in cases
        ]
        outcomes = await merge.merge_all(project_id, candidates)

        results: list[GeneratedCase] = []
        for case, code, outcome in zip(cases, codes, outcomes, strict=True):
            test_script = await script_repo.add(
                _to_test_script(
                    project_id, outcome.test_case.id, code, self._generated_by
                )
            )
            results.append(
                GeneratedCase(case, outcome.test_case, test_script, outcome.action)
            )

        by_oracle = Counter(c.oracle_source.value for c in cases)
        logger.info(
            "generation.completed",
            extra={
                "method": spec.method,
                "uri": spec.uri,
                "case_count": len(cases),
                "oracle_sources": dict(by_oracle),
            },
        )
        return results
