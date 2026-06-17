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

from app.models.enums import Outcome, RunMode, RunTrigger
from app.models.result import Result
from app.models.run import Run
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository

from .dual_db import ensure_safe_target
from .errors import ExecutionError
from .types import ExecutionRunner, PestScript, TargetEnv

logger = logging.getLogger("app.execution")

STATUS_RUNNING = "running"
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"  # ran to completion, but at least one test did not pass
STATUS_ERRORED = "errored"  # infra/runner failure — the run could not complete


def _now() -> datetime:
    return datetime.now(UTC)


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

        run = await run_repo.add(
            Run(
                project_id=project_id,
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
                    )
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
