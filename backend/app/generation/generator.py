"""TestGenerator — orchestrates plan → render → persist (Standards §5).

Planning is fully deterministic; the AIProvider only renders. Persists each case
to test_cases and each rendered script to test_scripts (project-scoped,
authored_by=ai, deterministic=false). Does NOT execute the tests (that is T1.5).
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from dataclasses import asdict, dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.types import AIProvider
from app.ingestion.models import EndpointSpec
from app.models.enums import AuthoredBy, Framework, TestLayer
from app.models.test_case import TestCase
from app.models.test_script import TestScript
from app.repositories.test_case_repository import TestCaseRepository
from app.repositories.test_script_repository import TestScriptRepository

from .plan import PlannedCase, plan_cases
from .render import render_script

logger = logging.getLogger("app.generation")


@dataclass
class GeneratedCase:
    plan: PlannedCase
    test_case: TestCase
    test_script: TestScript


def _to_test_case(
    project_id: uuid.UUID, spec: EndpointSpec, case: PlannedCase
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
        self, *, provider: AIProvider, budget_tokens: int, generated_by: str
    ) -> None:
        self._provider = provider
        self._budget = budget_tokens
        self._generated_by = generated_by

    def plan(self, spec: EndpointSpec) -> list[PlannedCase]:
        """PHASE 1 — pure, deterministic, AI-free."""
        return plan_cases(spec)

    async def generate_and_persist(
        self, *, session: AsyncSession, project_id: uuid.UUID, spec: EndpointSpec
    ) -> list[GeneratedCase]:
        cases = self.plan(spec)
        case_repo = TestCaseRepository(session)
        script_repo = TestScriptRepository(session)

        results: list[GeneratedCase] = []
        for case in cases:
            code = render_script(self._provider, spec, case, self._budget)
            test_case = await case_repo.add(_to_test_case(project_id, spec, case))
            test_script = await script_repo.add(
                _to_test_script(project_id, test_case.id, code, self._generated_by)
            )
            results.append(GeneratedCase(case, test_case, test_script))

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
