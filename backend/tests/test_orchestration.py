"""Walking-skeleton orchestration wiring — StubAIProvider + fixture, no real model.

Exercises run_walking_skeleton end to end with an injected extractor (returns the
fixture EndpointSpec), the deterministic StubAIProvider, and an all-pass fake
runner (the real PestRunner is integration-tested in the runner image). Asserts
the run, cases/scripts/results, the coverage row, and the report are produced.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.stub import StubAIProvider
from app.execution.types import (
    DbHandle,
    DbRole,
    ExecutionResult,
    PestScript,
    TargetEnv,
)
from app.generation.generator import TestGenerator
from app.ingestion.laravel.route_list import RouteTarget
from app.ingestion.models import EndpointSpec
from app.models.enums import Outcome
from app.repositories.coverage_repository import CoverageRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from app.repositories.test_script_repository import TestScriptRepository
from app.reporting.orchestrator import run_walking_skeleton
from tests.factories import make_project

_ENV = TargetEnv(
    app_path="/unused",
    execution_db=DbHandle("sqlite::memory:", DbRole.WRITABLE_TEST, ephemeral=True),
    evidence_dir="/unused",
)


class _FakeExtractor:
    def __init__(self, spec: EndpointSpec) -> None:
        self._spec = spec

    def extract_endpoint(self, repo_path: str, target: RouteTarget) -> EndpointSpec:
        return self._spec


class _AllPassRunner:
    framework = "pest"

    def run(
        self, scripts: list[PestScript], target_env: TargetEnv
    ) -> list[ExecutionResult]:
        return [
            ExecutionResult(
                test_case_id=s.test_case_id,
                script_id=s.script_id,
                name=s.name,
                outcome=Outcome.PASS,
                evidence_ref="/ev/pest-junit.xml",
            )
            for s in scripts
        ]

    def teardown(self, target_env: TargetEnv) -> None:
        pass


@pytest.fixture(autouse=True)
def _forbid_real_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("real `claude -p` subprocess invoked in tests")

    monkeypatch.setattr("app.ai.claude_cli.subprocess.run", _boom)


async def test_run_walking_skeleton_chains_extract_generate_execute_report(
    db_session: AsyncSession, endpoint_spec: object
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()

    report = await run_walking_skeleton(
        session=db_session,
        project_id=project.id,
        repo_path="/repo",
        route_target=RouteTarget(name="users.store"),
        extractor=_FakeExtractor(endpoint_spec),  # type: ignore[arg-type]
        generator=TestGenerator(
            provider=StubAIProvider(), budget_tokens=4096, generated_by="stub"
        ),
        runner=_AllPassRunner(),
        target_env=_ENV,
    )

    # Report: the full fixture endpoint, oracle-honest breakdown, all green.
    assert report.endpoint == "POST /api/users"
    assert report.total == 14
    assert report.outcomes == {"pass": 14, "fail": 0, "error": 0}
    assert report.oracle.rule_derived == 13
    assert report.oracle.characterization == 1
    assert report.oracle.spec_grounded == 0
    assert "Oracle honesty:" in report.render()

    # The full chain persisted: cases, scripts, a run, results, and coverage.
    assert len(await TestCaseRepository(db_session).list(project.id)) == 14
    assert len(await TestScriptRepository(db_session).list(project.id)) == 14

    runs = await RunRepository(db_session).list(project.id)
    assert len(runs) == 1 and runs[0].status == "passed"

    results = await ResultRepository(db_session).list_for_run(project.id, runs[0].id)
    assert len(results) == 14
    assert all(r.triage is None for r in results)

    coverage = await CoverageRepository(db_session).list_for_run(project.id, runs[0].id)
    assert len(coverage) == 1
    cov = coverage[0]
    assert cov.dimension.value == "endpoint"
    assert cov.covered["endpoints"] == ["POST /api/users"]
    assert cov.covered["oracle_honesty"]["characterization"] == 1
    assert "characterization-only" in cov.gaps["notes"][0]
