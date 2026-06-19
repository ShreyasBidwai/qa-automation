"""E2EGenerator — cross-layer journey → deterministic plan → AI spec → persist.

Mirrors the backend TestGenerator: planning is fully deterministic (e2e_plan),
the AIProvider only renders (e2e_render), the mutation-kill gate rejects
tautological oracles before anything is written, and persistence goes through the
T3.2 CaseMergeService so re-running generation is idempotent-by-``case_key`` and
NEVER clobbers a human edit (a re-gen of a human-edited case lands as a proposal,
not an overwrite). Does NOT execute the spec (that is the T4.1 runner).
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.types import AIProvider
from app.brain.cross_layer import CrossLayerResolver
from app.models.enums import AuthoredBy, CaseOrigin, Framework, TestLayer
from app.models.model_node import ModelNode
from app.models.test_case import TestCase
from app.models.test_script import TestScript
from app.repositories.test_script_repository import TestScriptRepository
from app.services.case_merge_service import CaseMergeService, MergeAction

from .e2e_plan import PlannedE2ECase, build_e2e_plan, e2e_case_key
from .e2e_render import render_e2e_spec
from .mutation_gate import enforce_mutation_gate

logger = logging.getLogger("app.generation.e2e")


@dataclass
class GeneratedE2ECase:
    plan: PlannedE2ECase
    test_case: TestCase
    test_script: TestScript
    action: MergeAction  # how the merge engine reconciled this case


def _to_test_case(
    project_id: uuid.UUID, page: ModelNode, case: PlannedE2ECase
) -> TestCase:
    return TestCase(
        project_id=project_id,
        type=case.case_type,
        layer=TestLayer.UI,
        target_node=page.id,  # the page node this E2E case drives
        preconditions={"page": {"path": case.page_path, "node": page.name}},
        steps={"case": case.name, "steps": [s.to_dict() for s in case.steps]},
        expected={"assertions": [a.to_dict() for a in case.assertions]},
        oracle_source=case.oracle_source,
        authored_by=AuthoredBy.AI,
        edited_by_human=False,
        origin=CaseOrigin.GENERATED,
        case_key=e2e_case_key(case.page_path, case.name),
    )


def _to_test_script(
    project_id: uuid.UUID, test_case_id: uuid.UUID, code: str, generated_by: str
) -> TestScript:
    return TestScript(
        project_id=project_id,
        test_case_id=test_case_id,
        framework=Framework.PLAYWRIGHT,
        code=code,
        generated_by=generated_by,
        deterministic=False,  # the plan is deterministic; the rendered spec is AI
    )


class E2EGenerator:
    def __init__(
        self, *, provider: AIProvider, budget_tokens: int, generated_by: str
    ) -> None:
        self._provider = provider
        self._budget = budget_tokens
        self._generated_by = generated_by

    async def generate_and_persist(
        self, *, session: AsyncSession, project_id: uuid.UUID, page_node_id: uuid.UUID
    ) -> list[GeneratedE2ECase]:
        # PHASE 1 — deterministic plan from the cross-layer journey (no AI).
        journey = await CrossLayerResolver(session).journey(project_id, page_node_id)
        plan = build_e2e_plan(journey)
        enforce_mutation_gate(plan)  # reject tautological oracles before writing

        merge = CaseMergeService(session)
        script_repo = TestScriptRepository(session)

        results: list[GeneratedE2ECase] = []
        for case in plan:
            # PHASE 2 — AI renders the spec AROUND the fixed plan/assertions.
            code = render_e2e_spec(self._provider, case, self._budget)
            outcome = await merge.merge(
                project_id, _to_test_case(project_id, journey.root, case)
            )
            script = await script_repo.add(
                _to_test_script(
                    project_id, outcome.test_case.id, code, self._generated_by
                )
            )
            results.append(
                GeneratedE2ECase(case, outcome.test_case, script, outcome.action)
            )

        by_action = Counter(r.action for r in results)
        logger.info(
            "generation.e2e.completed",
            extra={
                "project_id": str(project_id),
                "page_node_id": str(page_node_id),
                "case_count": len(results),
                "actions": dict(by_action),
            },
        )
        return results
