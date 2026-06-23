"""Run lifecycle — create a run, execute, persist results, finalize (TRD §5/§8).

Orchestrates one execution against the writable test DB: opens a ``runs`` row,
runs the injected ExecutionRunner, persists each result as a ``results`` row
(project-scoped, tied to the run, triage null until Sprint 7), and updates the
run status. Teardown runs on completion AND on failure (Standards §11) so no
target app state or test DB leaks.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app import progress
from app.models.enums import Outcome, RunMode, RunTrigger
from app.models.result import Result
from app.models.run import Run
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.screenshots import store_screenshot

from .dual_db import ensure_safe_target
from .errors import ExecutionError
from .types import ExecutionResult, ExecutionRunner, PestScript, TargetEnv

logger = logging.getLogger("app.execution")

STATUS_RUNNING = "running"
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"  # ran to completion, but at least one test did not pass
STATUS_ERRORED = "errored"  # infra/runner failure — the run could not complete


def _now() -> datetime:
    return datetime.now(UTC)


def _capture_screenshot(run_id: uuid.UUID, result: ExecutionResult) -> str | None:
    """Store a failing result's screenshot via the single indirection (ADR-0051).

    Best-effort + side-effect-safe: only fires for a FAILING result that carries
    bytes, and any storage failure is logged, never raised — capturing a screenshot
    can't break or fail a run (the same rule as incident capture).
    """
    if result.outcome is Outcome.PASS or result.screenshot is None:
        return None
    try:
        return store_screenshot(result.screenshot)
    except Exception:  # noqa: BLE001 — screenshot capture is best-effort, never fatal
        logger.warning(
            "execution.screenshot_capture_failed", extra={"run_id": str(run_id)}
        )
        return None


class RunLifecycle:
    def __init__(self, *, runner: ExecutionRunner) -> None:
        self._runner = runner

    async def execute(
        self,
        *,
        session: AsyncSession,
        project_id: uuid.UUID,
        scripts: list[PestScript],
        target_env: TargetEnv,
        trigger: RunTrigger,
        mode: RunMode,
        commit_sha: str | None = None,
    ) -> Run:
        run_repo = RunRepository(session)
        result_repo = ResultRepository(session)

        # Claim the friendly per-project run number atomically (ADR-0048) before the
        # run row is created, so every run carries a stable "#N".
        run_number = await run_repo.next_run_number(project_id)
        run = await run_repo.add(
            Run(
                project_id=project_id,
                run_number=run_number,
                trigger=trigger,
                mode=mode,
                commit_sha=commit_sha,
                status=STATUS_RUNNING,
                started_at=_now(),
            )
        )

        status = STATUS_ERRORED
        try:
            ensure_safe_target(target_env)  # dual-DB safety before any execution
            # Run-progress (ADR-0050): the execute phase + a per-test step as each
            # result lands — this is the journey the live view renders. Best-effort.
            await progress.emit(
                phase=progress.PHASE_EXECUTE,
                step=f"Execute {len(scripts)} tests",
                status=progress.STATUS_STARTED,
                detail={"tests": len(scripts)},
            )
            exec_results = self._runner.run(scripts, target_env)
            for er in exec_results:
                await result_repo.add(
                    Result(
                        project_id=project_id,
                        run_id=run.id,
                        test_case_id=er.test_case_id,
                        outcome=er.outcome,
                        triage=None,  # Sprint 7
                        evidence_ref=er.evidence_ref,
                        # Failure screenshot (ADR-0051); the assembler copies the ref
                        # onto the finding. Best-effort — never breaks the run.
                        screenshot_ref=_capture_screenshot(run.id, er),
                        message=er.message,  # B8: detail for heal classification
                    )
                )
                await progress.emit(
                    phase=progress.PHASE_EXECUTE,
                    step=er.name,
                    status=(
                        progress.STATUS_PASSED
                        if er.outcome is Outcome.PASS
                        else progress.STATUS_FAILED
                    ),
                    detail={"test": er.name, "outcome": er.outcome.value},
                )
            status = (
                STATUS_PASSED
                if all(er.outcome is Outcome.PASS for er in exec_results)
                else STATUS_FAILED
            )
        finally:
            run.status = status
            run.finished_at = _now()
            await session.flush()
            # Teardown always runs (completion or failure); never mask the
            # primary error if cleanup itself fails.
            try:
                self._runner.teardown(target_env)
            except ExecutionError:
                logger.warning(
                    "execution.teardown_failed", extra={"run_id": str(run.id)}
                )

        logger.info(
            "execution.completed",
            extra={"run_id": str(run.id), "status": status, "count": len(scripts)},
        )
        return run
