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
from .errors import ExecutionError, MissingTestRunnerError
from .types import ExecutionResult, ExecutionRunner, PestScript, TargetEnv

logger = logging.getLogger("app.execution")

STATUS_RUNNING = "running"
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"  # ran to completion, but at least one test did not pass
STATUS_ERRORED = "errored"  # infra/runner failure — the run could not complete
STATUS_INTERRUPTED = "interrupted"  # crashed mid-run (e.g. DB outage) — reconciled
#   from a stale "running" by the worker (run-durability); the partial run + the
#   cases committed so far survive, rather than rolling back to nothing.


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

    async def start(
        self,
        *,
        session: AsyncSession,
        project_id: uuid.UUID,
        trigger: RunTrigger,
        mode: RunMode,
        commit_sha: str | None = None,
    ) -> Run:
        """Create and COMMIT the run row (status=running) BEFORE any generation.

        Run-durability: the row is durable from t=0, so a crash mid-run leaves a
        real, reconcilable run (marked interrupted by the worker) instead of rolling
        back to nothing. Its id is PINNED to the active run handle (the RUN job id,
        via the installed progress emitter) when there is one, so the runs row and
        the user-facing ``/runs/{id}`` are the same identity; off the run path
        (tests / no emitter) the row gets its own id.
        """
        run_repo = RunRepository(session)
        # Claim the friendly per-project run number atomically (ADR-0048) before the
        # run row is created, so every run carries a stable "#N".
        run_number = await run_repo.next_run_number(project_id)
        pinned = progress.current_run_id()
        run = await run_repo.add(
            Run(
                **({"id": pinned} if pinned is not None else {}),
                project_id=project_id,
                run_number=run_number,
                trigger=trigger,
                mode=mode,
                commit_sha=commit_sha,
                status=STATUS_RUNNING,
                started_at=_now(),
            )
        )
        await session.commit()  # durable from t=0 (survives a later mid-run crash)
        return run

    async def run_scripts(
        self,
        *,
        session: AsyncSession,
        run: Run,
        scripts: list[PestScript],
        target_env: TargetEnv,
    ) -> Run:
        """Execute the scripts against an already-persisted run, persist results,
        finalize the status, and tear down. Commits the results + terminal status so
        they are durable (a DB-level failure here leaves the row 'running' for the
        worker's reconcile sweep)."""
        result_repo = ResultRepository(session)

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
            try:
                exec_results = self._runner.run(scripts, target_env)
            except MissingTestRunnerError as exc:
                # No local composer-installed checkout → the API/Pest layer has
                # nothing runnable (e.g. the project's repo_url is a git URL used for
                # INGEST, with no /targets/app mounted). SKIP the API layer honestly
                # and let the run CONTINUE (the UI crawl needs only the app URL),
                # rather than failing the whole run. The generated cases persist and
                # re-run once a checkout is present.
                logger.info(
                    "execution.api_skipped_no_runner",
                    extra={"run_id": str(run.id), "reason": str(exc)},
                )
                await progress.emit(
                    phase=progress.PHASE_EXECUTE,
                    step=f"Execute {len(scripts)} tests",
                    status=progress.STATUS_SKIPPED,
                    detail={
                        "skipped": (
                            "no local checkout for the API runner — run "
                            "`composer install` in the target, or run the UI layer"
                        )
                    },
                )
                exec_results = []
            for er in exec_results:
                # Capture once: the row carries it (the assembler copies it onto the
                # finding) AND the live view serves it as the step's frame, so a
                # failing test is watchable with its screenshot. Best-effort (ADR-0051).
                shot_ref = _capture_screenshot(run.id, er)
                await result_repo.add(
                    Result(
                        project_id=run.project_id,
                        run_id=run.id,
                        test_case_id=er.test_case_id,
                        outcome=er.outcome,
                        triage=None,  # Sprint 7
                        evidence_ref=er.evidence_ref,
                        screenshot_ref=shot_ref,
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
                    screenshot_ref=shot_ref,
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
            # Persist the terminal status + results durably, even on failure
            # (best-effort: a DB-level failure leaves the row 'running' for the
            # reconcile sweep, and must never mask the primary error).
            try:
                await session.commit()
            except Exception:  # noqa: BLE001 — never mask the original failure
                logger.warning(
                    "execution.finalize_commit_failed",
                    extra={"run_id": str(run.id)},
                )

        logger.info(
            "execution.completed",
            extra={"run_id": str(run.id), "status": status, "count": len(scripts)},
        )
        return run

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
        """Create the run row then execute its scripts — ``start`` + ``run_scripts``
        in one call. The Mode B path calls the two halves separately (so it can
        generate, committing per case, between them); this wrapper keeps the
        single-shot path (Mode A/C, tests) intact."""
        run = await self.start(
            session=session,
            project_id=project_id,
            trigger=trigger,
            mode=mode,
            commit_sha=commit_sha,
        )
        return await self.run_scripts(
            session=session, run=run, scripts=scripts, target_env=target_env
        )
