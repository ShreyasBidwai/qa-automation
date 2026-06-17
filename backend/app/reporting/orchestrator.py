"""run_walking_skeleton — the fully-assembled Sprint 1 skeleton (project plan §1).

One entrypoint that chains extract -> generate -> execute -> report for ONE
endpoint: it creates the run, persists cases/scripts/results/coverage, and returns
the rendered report. Collaborators are injected (Standards §5) so the same
entrypoint serves the offline test (StubAIProvider + fake runner) and the real
manual gate (claude_cli provider + PestRunner against the Laravel image).
"""

from __future__ import annotations

import logging
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.lifecycle import RunLifecycle
from app.execution.types import ExecutionRunner, PestScript, TargetEnv
from app.generation.generator import TestGenerator
from app.ingestion.laravel.route_list import RouteTarget
from app.ingestion.models import EndpointSpec
from app.models.enums import RunMode, RunTrigger
from app.repositories.result_repository import ResultRepository

from .report import RunReport, build_report, persist_coverage

logger = logging.getLogger("app.reporting")


class EndpointExtractor(Protocol):
    """Structural type for the extraction step (LaravelExtractor conforms)."""

    def extract_endpoint(self, repo_path: str, target: RouteTarget) -> EndpointSpec: ...


async def run_walking_skeleton(
    *,
    session: AsyncSession,
    project_id: uuid.UUID,
    repo_path: str,
    route_target: RouteTarget,
    extractor: EndpointExtractor,
    generator: TestGenerator,
    runner: ExecutionRunner,
    target_env: TargetEnv,
    trigger: RunTrigger = RunTrigger.MANUAL,
    mode: RunMode = RunMode.C,
    commit_sha: str | None = None,
) -> RunReport:
    # 1. EXTRACT — one endpoint's normalized spec (deterministic, no AI).
    spec = extractor.extract_endpoint(repo_path, route_target)

    # 2. GENERATE — deterministic plan + AI-rendered scripts, persisted.
    generated = await generator.generate_and_persist(
        session=session, project_id=project_id, spec=spec
    )
    scripts = [
        PestScript(
            test_case_id=g.test_case.id,
            script_id=g.test_script.id,
            name=g.plan.name,
            code=g.test_script.code,
        )
        for g in generated
    ]

    # 3. EXECUTE — create the run, run the suite against the test DB, persist
    #    results, finalize status (with no-leak teardown).
    run = await RunLifecycle(runner=runner).execute(
        session=session,
        project_id=project_id,
        scripts=scripts,
        target_env=target_env,
        trigger=trigger,
        mode=mode,
        commit_sha=commit_sha,
    )
    results = await ResultRepository(session).list_for_run(project_id, run.id)

    # 4. REPORT — the oracle-honest summary; persist the coverage row.
    report = build_report(spec=spec, generated=generated, run=run, results=results)
    await persist_coverage(
        session=session, project_id=project_id, run=run, report=report
    )

    logger.info(
        "walking_skeleton.completed",
        extra={
            "endpoint": report.endpoint,
            "run_id": str(run.id),
            "status": run.status,
            "case_count": report.total,
        },
    )
    return report
