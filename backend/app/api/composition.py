"""Compose the run/ingest provider ports for the running server (packaging).

``create_app`` deliberately leaves ``app.state.run_executor`` / ``ingestor``
unset (``None`` → routes 503) so the fast lane stubs the ports per-test. The real
server (``app.__main__``) composes them here from settings, DEFAULTING to safe
stubs so a clone boots and a run completes end-to-end with zero external
credentials or toolchains (docs/running.md).

Why stubs by default: a real run shells out to the Pest/Playwright toolchains as
subprocesses of the backend process (see ``app.execution``); the packaged backend
image ships none of them. Real execution (``executor_mode=orchestrator``) and real
ingestion (``ingestor_mode=laravel``) are a documented opt-in, not wired into the
packaged image.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.factory import build_ai_provider
from app.core.config import Settings
from app.embeddings.factory import build_embedding_provider
from app.incidents import capturing_ai_provider, capturing_embedding_provider
from app.models.enums import (
    AuthoredBy,
    FindingLayer,
    OracleSource,
    Outcome,
    RunMode,
    RunTrigger,
    TestLayer,
    TestType,
)
from app.models.finding import Finding
from app.models.finding_result import FindingResult
from app.models.result import Result
from app.models.run import Run
from app.models.test_case import TestCase
from app.progress import (
    PHASE_EXECUTE,
    PHASE_GENERATE,
    PHASE_REVIEW,
    PHASE_RUN,
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_STARTED,
    emit,
)
from app.repositories.project_repository import ProjectRepository
from app.screenshots import placeholder_screenshot, store_screenshot

from .errors import ApiConfigError
from .ports import Ingestor, RunExecution, RunExecutor, RunRequest

logger = logging.getLogger("app.api.composition")


def _store_demo_screenshot() -> str | None:
    """A placeholder screenshot for the demo failing finding (ADR-0051).

    Best-effort + side-effect-safe: a storage failure is logged, never raised — so
    the stub run completes regardless (the same rule as a real capture)."""
    try:
        return store_screenshot(placeholder_screenshot())
    except Exception:  # noqa: BLE001 — screenshot capture must never break a run
        logger.warning("composition.stub_screenshot_failed")
        return None


# The fabricated demo finding's shape — a believable, fully-detailed bug so the
# clone→up walkthrough exercises the whole finding flow (detail drawer, triage).
_DEMO_KEY = "endpoint=POST api/orders#fail|status=500"
_DEMO_EXPECTED: dict[str, Any] = {"status": 500, "assertions": [{"kind": "status"}]}
_DEMO_LOCATION: dict[str, Any] = {
    "page": "/checkout",
    "endpoints": ["POST api/orders"],
    "tables": ["orders"],
}
_DEMO_EVIDENCE = "stub://evidence/demo-trace.zip"


class StubRunExecutor:
    """A zero-dependency executor that fabricates one believable demo finding.

    Honest by construction: it runs no tests and calls no AI — it persists a
    clearly-labelled *stub* run + finding so the running stack shows the full
    finding experience without toolchains. ``mode_c`` produces no run (authoring).
    """

    async def execute(
        self,
        *,
        session: AsyncSession,
        project_id: uuid.UUID,
        request: RunRequest,
    ) -> RunExecution:
        if request.mode is RunMode.C:
            return RunExecution(
                run_id=None,
                summary={"mode": "stub", "note": "authoring stub — no run produced"},
            )

        project = await ProjectRepository(session).get(project_id)
        target = project.name if project is not None else "Stub demo run"

        # A believable progress journey so the live run view can be built + demoed
        # before real execution (ADR-0050). Best-effort: no-op without an emitter.
        await emit(phase=PHASE_RUN, step="run", status=STATUS_STARTED)
        await emit(
            phase=PHASE_GENERATE,
            step="Generate test for POST api/orders",
            status=STATUS_PASSED,
            detail={"endpoint": "POST api/orders"},
        )

        run = Run(
            project_id=project_id,
            trigger=RunTrigger.MANUAL,
            mode=RunMode.B,
            status="failed",
        )
        session.add(run)
        await session.flush()

        case = TestCase(
            project_id=project_id,
            type=TestType.NEGATIVE,
            layer=TestLayer.API,
            oracle_source=OracleSource.RULE_DERIVED,
            authored_by=AuthoredBy.AI,
            expected=_DEMO_EXPECTED,
        )
        session.add(case)
        await session.flush()

        await emit(
            phase=PHASE_EXECUTE,
            step="Execute 1 test",
            status=STATUS_STARTED,
            detail={"tests": 1},
        )
        screenshot_ref = _store_demo_screenshot()
        result = Result(
            project_id=project_id,
            run_id=run.id,
            test_case_id=case.id,
            outcome=Outcome.FAIL,
            evidence_ref=_DEMO_EVIDENCE,
            screenshot_ref=screenshot_ref,
        )
        session.add(result)
        await session.flush()
        await emit(
            phase=PHASE_EXECUTE,
            step="POST api/orders returns 201",
            status=STATUS_FAILED,
            detail={"endpoint": "POST api/orders", "expected": 201, "actual": 500},
        )

        finding = Finding(
            project_id=project_id,
            run_id=run.id,
            result_id=result.id,
            root_cause_key=_DEMO_KEY,
            explains_count=1,
            title="api failure at POST api/orders (stub demo)",
            layer=FindingLayer.API,
            oracle_source=OracleSource.RULE_DERIVED,
            confidence_mixed=False,
            expected=_DEMO_EXPECTED,
            location=_DEMO_LOCATION,
            evidence_ref=_DEMO_EVIDENCE,
            screenshot_ref=screenshot_ref,
            severity="major",
            status="new",
        )
        session.add(finding)
        await session.flush()

        session.add(
            FindingResult(
                project_id=project_id, finding_id=finding.id, result_id=result.id
            )
        )
        await session.flush()

        await emit(
            phase=PHASE_REVIEW,
            step="Review complete",
            status=STATUS_PASSED,
            detail={"findings": 1},
        )
        # Terminal run event — ends the live stream (the stub run "failed").
        await emit(
            phase=PHASE_RUN,
            step="run",
            status=STATUS_FAILED,
            detail={"status": "failed", "findings": 1},
        )

        return RunExecution(
            run_id=run.id,
            summary={
                "mode": "stub",
                "target": target,
                "pass_rate": 0.0,
                "failed": 1,
                "errors": 0,
                "coverage": 0.0,
                "findings": 1,
                "project_id": str(project_id),
                "note": "stub run — fabricated demo finding, no tests executed "
                "(docs/running.md)",
            },
        )


class StubIngestor:
    """A no-op ingestor: records an honest stub summary, builds no Brain."""

    async def ingest(
        self, *, session: AsyncSession, project_id: uuid.UUID
    ) -> dict[str, Any]:
        return {
            "mode": "stub",
            "nodes": 0,
            "edges": 0,
            "note": "stub ingestor — no Brain built (real ingestion needs git + "
            "the source adapter; docs/running.md)",
        }


def build_run_executor(settings: Settings) -> RunExecutor:
    """Resolve the run-executor port from settings.

    ``stub`` → the zero-dependency demo executor. ``orchestrator`` → the FULLY-WIRED
    real executor: a real per-stack runner + target env, the AI/embedding providers
    (from the factories), and the session-scoped Brain resolver + AI-backed target
    generator built per run (the B5 gap, now closed). Only a runner worker that
    carries the toolchains composes this (ADR-0036).
    """
    if settings.executor_mode == "stub":
        return StubRunExecutor()
    if settings.executor_mode == "orchestrator":
        from app.brain.cross_layer import CrossLayerResolver
        from app.ingestion.laravel.factories import target_has_factories

        from .execution import OrchestratorRunExecutor
        from .real_execution import (
            OrchestratorTargetGenerator,
            build_runner,
            build_target_env,
        )

        ai_provider = build_ai_provider(settings)
        embedding_provider = build_embedding_provider(settings)
        budget = settings.ai_max_budget_tokens
        # Whether generated tests may use model factories (ADR-0037).
        factories = target_has_factories(settings.target_repo_path)
        return OrchestratorRunExecutor(
            runner=build_runner(settings),
            target_env=build_target_env(settings),
            # Session-scoped: built per run from the job's session.
            resolver_factory=CrossLayerResolver,
            # The generator is where provider calls actually happen during a run;
            # wrap them so a provider failure is tagged + captured as `provider`
            # (ADR-0047). The executor's own _ai/_embed stay the raw composed types.
            target_generator_factory=lambda session: OrchestratorTargetGenerator(
                session,
                ai_provider=capturing_ai_provider(ai_provider),
                budget_tokens=budget,
                factories_available=factories,
                embedding_provider=capturing_embedding_provider(embedding_provider),
            ),
            ai_provider=ai_provider,
            embedding_provider=embedding_provider,
        )
    raise ApiConfigError(
        f"unknown executor_mode {settings.executor_mode!r} "
        "(expected 'stub' or 'orchestrator')"
    )


def build_ingestor(settings: Settings) -> Ingestor:
    """Resolve the ingestor port from settings.

    ``stub`` → no-op. ``laravel`` → the real Laravel ingestor (reads the repo,
    builds the Brain). Only a runner worker with PHP/Composer + git composes this.
    """
    if settings.ingestor_mode == "stub":
        return StubIngestor()
    if settings.ingestor_mode == "laravel":
        from .real_execution import LaravelIngestorAdapter

        return LaravelIngestorAdapter(
            repo_path=settings.target_repo_path,
            embedding_provider=capturing_embedding_provider(
                build_embedding_provider(settings)
            ),
        )
    raise ApiConfigError(
        f"unknown ingestor_mode {settings.ingestor_mode!r} "
        "(expected 'stub' or 'laravel')"
    )
