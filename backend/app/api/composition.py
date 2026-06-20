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

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
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
from app.repositories.project_repository import ProjectRepository

from .errors import ApiConfigError
from .ports import Ingestor, RunExecution, RunExecutor, RunRequest

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

        result = Result(
            project_id=project_id,
            run_id=run.id,
            test_case_id=case.id,
            outcome=Outcome.FAIL,
            evidence_ref=_DEMO_EVIDENCE,
        )
        session.add(result)
        await session.flush()

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
    """Resolve the run-executor port from settings (default: stub)."""
    if settings.executor_mode == "stub":
        return StubRunExecutor()
    raise ApiConfigError(
        f"executor_mode={settings.executor_mode!r} requires the orchestrator + "
        "runner toolchains, which are not wired into the packaged image "
        "(docs/running.md)."
    )


def build_ingestor(settings: Settings) -> Ingestor:
    """Resolve the ingestor port from settings (default: stub)."""
    if settings.ingestor_mode == "stub":
        return StubIngestor()
    raise ApiConfigError(
        f"ingestor_mode={settings.ingestor_mode!r} requires git + the source "
        "adapter, which are not wired into the packaged image (docs/running.md)."
    )
