"""Persistence — cases + scripts persist project-scoped, ai-authored, non-det."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.stub import StubAIProvider
from app.generation.generator import TestGenerator
from app.models.enums import AuthoredBy, Framework, OracleSource, TestLayer
from app.repositories.test_case_repository import TestCaseRepository
from app.repositories.test_script_repository import TestScriptRepository
from tests.factories import make_project


async def test_cases_and_scripts_persist_correctly(
    db_session: AsyncSession, endpoint_spec: object
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()

    generator = TestGenerator(
        provider=StubAIProvider(), budget_tokens=120_000, generated_by="stub"
    )
    results = await generator.generate_and_persist(
        session=db_session, project_id=project.id, spec=endpoint_spec  # type: ignore[arg-type]
    )
    assert len(results) == 14

    cases = await TestCaseRepository(db_session).list(project.id)
    scripts = await TestScriptRepository(db_session).list(project.id)
    assert len(cases) == 14
    assert len(scripts) == 14

    for test_case in cases:
        assert test_case.project_id == project.id
        assert test_case.layer == TestLayer.API
        assert test_case.authored_by == AuthoredBy.AI
        assert test_case.edited_by_human is False
        assert test_case.version == 1
        assert test_case.target_node is None
        # endpoint identity stored in preconditions (no target_node FK yet)
        assert test_case.preconditions["endpoint"]["uri"] == "api/users"

    for script in scripts:
        assert script.project_id == project.id
        assert script.framework == Framework.PEST
        assert script.deterministic is False
        assert script.generated_by == "stub"
        assert script.code.strip()

    sources = [tc.oracle_source for tc in cases]
    assert sources.count(OracleSource.CHARACTERIZATION) == 1
    assert sources.count(OracleSource.RULE_DERIVED) == 13
    assert sources.count(OracleSource.SPEC_GROUNDED) == 0


async def test_happy_script_carries_characterization_comment(
    db_session: AsyncSession, endpoint_spec: object
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()

    generator = TestGenerator(
        provider=StubAIProvider(), budget_tokens=4096, generated_by="stub"
    )
    results = await generator.generate_and_persist(
        session=db_session, project_id=project.id, spec=endpoint_spec  # type: ignore[arg-type]
    )

    happy = next(r for r in results if r.plan.name == "happy")
    assert "CHARACTERIZATION" in happy.test_script.code
    assert "oracle_source: characterization" in happy.test_script.code

    rule_derived = next(r for r in results if r.plan.name == "age_required_missing")
    assert "CHARACTERIZATION" not in rule_derived.test_script.code
    assert "oracle_source: rule-derived" in rule_derived.test_script.code
