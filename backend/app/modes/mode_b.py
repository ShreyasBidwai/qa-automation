"""Mode B — the autonomous orchestrator (T8.2, closes Sprint 8).

The hands-off loop with no human in it: select what to test from the Brain, ensure
a current case exists for each target, execute, and produce findings — bounded and
deterministic (ADR-0025). Orchestration ONLY: every heavy collaborator is reused,
not reimplemented — the selection strategies (selection.py, wrapping the T8.1
ImpactSelector), an injected ``TargetGenerator`` (wrapping the existing
generators), the runner via ``RunLifecycle``, and the finding pipeline
(assemble → score → classify → rank).

Honesty propagation: if the strategy reports ``scope_uncertain`` (the T8.1 widen
rule), Mode B discards the narrowed selection and runs a full sweep — it never
executes a narrowed set when scope is uncertain. Project-scoped throughout.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.usage import UsageCollector, install_collector, reset_collector
from app.brain.cross_layer import Impact, Subgraph
from app.db_state.run_phase import DbStatePhaseReport, DbStateRunPhase
from app.execution.lifecycle import STATUS_PASSED as RUN_STATUS_PASSED
from app.execution.lifecycle import RunLifecycle
from app.execution.types import ExecutionRunner, PestScript, TargetEnv
from app.models.ai_usage import AiUsage
from app.models.enums import RunMode, RunTrigger
from app.models.finding import Finding
from app.models.result import Result
from app.progress import (
    PHASE_GENERATE,
    PHASE_REVIEW,
    PHASE_RUN,
    PHASE_SELECT,
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_SKIPPED,
    STATUS_STARTED,
    emit,
)
from app.reporting import FindingAssembler, HistoryClassifier, SeverityScorer
from app.repositories.ai_usage_repository import AiUsageRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.test_case_repository import TestCaseRepository
from app.repositories.test_script_repository import TestScriptRepository

from .selection import (
    FullSweepStrategy,
    SelectionStrategy,
    SelectionStrategyKind,
    Target,
    targets_for_layers,
)

logger = logging.getLogger("app.modes.mode_b")


class BrainResolver(Protocol):
    """The cross-layer resolver Mode B's reporting needs (journey + impact).

    ``CrossLayerResolver`` conforms; injected so fast tests use a fake.
    """

    async def journey(
        self, project_id: uuid.UUID, node_id: uuid.UUID, max_depth: int = 3
    ) -> Subgraph: ...

    async def impact(self, project_id: uuid.UUID, node_id: uuid.UUID) -> Impact: ...


class TargetGenerator(Protocol):
    """Generate a runnable current case for a target via the existing generators.

    Reused, not reimplemented: a production impl dispatches endpoint → the
    deterministic backend generator and page → the E2E generator, persists via the
    never-clobber lifecycle, and returns the executable script. Injected so fast
    tests use a stub (no real generation).
    """

    async def generate(
        self, *, project_id: uuid.UUID, target: Target
    ) -> PestScript: ...


@dataclass(frozen=True)
class ModeBBounds:
    """The configured limits on one autonomous run (always applied)."""

    max_targets: int  # hard cap on how many targets a run drives
    max_seconds: float | None = None  # wall-clock budget for the ensure loop
    # Optional layer scope (ADR-0052): which of ui/api/db this run exercises. None =
    # the full set — targets are unfiltered and the DB-state phase runs as before.
    layers: frozenset[str] | None = None


@dataclass(frozen=True)
class EnsuredCase:
    """A runnable script for a target + whether it was generated or reused."""

    script: PestScript
    generated: bool


@dataclass(frozen=True)
class ModeBRunReport:
    """The outcome of one autonomous run: the run, the counts, the ranked findings."""

    run_id: uuid.UUID
    strategy: SelectionStrategyKind
    full_sweep_fallback: bool  # honesty: scope was uncertain → swept everything
    targets_selected: int
    cases_generated: int
    cases_reused: int
    status: str
    ranked_findings: tuple[Finding, ...]
    # DB-state phase outcome (B11, ADR-0044): None when no DB-state phase is wired
    # (default) or the project is ``off``; carries the refusal reason when the
    # non-prod gate refused the target. Additive — internal report only.
    db_state: DbStatePhaseReport | None = None


def _trigger_for(kind: SelectionStrategyKind) -> RunTrigger:
    if kind is SelectionStrategyKind.CHANGE_IMPACT:
        return RunTrigger.CHANGE_IMPACT
    return RunTrigger.CI  # autonomous full sweep is CI-like


class ModeBOrchestrator:
    def __init__(
        self,
        *,
        session: AsyncSession,
        runner: ExecutionRunner,
        target_env: TargetEnv,
        resolver: BrainResolver,
        generator: TargetGenerator,
        db_state: DbStateRunPhase | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session = session
        self._runner = runner
        self._target_env = target_env
        self._resolver = resolver
        self._generator = generator
        self._db_state = db_state
        self._clock = clock
        self._cases = TestCaseRepository(session)
        self._scripts = TestScriptRepository(session)

    async def run(
        self,
        *,
        project_id: uuid.UUID,
        strategy: SelectionStrategy,
        bounds: ModeBBounds,
    ) -> ModeBRunReport:
        """Select → ensure → execute → report, autonomously (deterministic, scoped).

        Wraps the run in an AI-usage collection context (ADR-0049): provider calls
        during generation buffer their usage here, and ``_run`` drains + persists it
        once the run row exists. Best-effort — capture never alters the run.
        """
        collector = UsageCollector()
        token = install_collector(collector)
        try:
            return await self._run(
                project_id=project_id,
                strategy=strategy,
                bounds=bounds,
                usage=collector,
            )
        finally:
            reset_collector(token)

    async def _run(
        self,
        *,
        project_id: uuid.UUID,
        strategy: SelectionStrategy,
        bounds: ModeBBounds,
        usage: UsageCollector,
    ) -> ModeBRunReport:
        requested_kind = strategy.kind
        # Run-progress (ADR-0050): the journey starts here and is narrated through
        # select → generate → execute → review to a terminal run event. Best-effort.
        await emit(phase=PHASE_RUN, step="run", status=STATUS_STARTED)
        selection = await strategy.select(project_id)

        full_sweep_fallback = False
        if selection.scope_uncertain:
            # HONESTY: never run a narrowed set when scope is uncertain (ADR-0025).
            logger.info(
                "modes.mode_b.scope_uncertain_full_sweep",
                extra={"project_id": str(project_id), "strategy": requested_kind.value},
            )
            selection = await FullSweepStrategy(self._session).select(project_id)
            full_sweep_fallback = True

        # Layer scope (ADR-0052): narrow to the requested layers' targets BEFORE the
        # count bound, so a UI-only run drives UI targets (None = full, unchanged).
        scoped = targets_for_layers(selection.targets, bounds.layers)
        targets = scoped[: bounds.max_targets]  # hard count bound
        await emit(
            phase=PHASE_SELECT,
            step=f"Select targets ({requested_kind.value})",
            status=STATUS_PASSED,
            detail={
                "targets": len(targets),
                "full_sweep_fallback": full_sweep_fallback,
                "layers": sorted(bounds.layers) if bounds.layers else None,
            },
        )
        # Run-durability: persist the run row (status=running) BEFORE generation, so
        # a crash mid-generation leaves a real, reconcilable run — not a rollback to
        # nothing. ``_ensure_cases`` then commits each generated case as it lands, so
        # a crash loses at most the in-flight target, never the whole run's work.
        lifecycle = RunLifecycle(runner=self._runner)
        run = await lifecycle.start(
            session=self._session,
            project_id=project_id,
            trigger=_trigger_for(requested_kind),
            mode=RunMode.B,
        )
        ensured = await self._ensure_cases(project_id, targets, bounds)
        scripts = [e.script for e in ensured]
        generated = sum(1 for e in ensured if e.generated)

        run = await lifecycle.run_scripts(
            session=self._session,
            run=run,
            scripts=scripts,
            target_env=self._target_env,
        )
        # Attribute + persist the AI usage buffered during generation now that the
        # run row exists (best-effort; ADR-0049).
        await self._flush_usage(project_id, run.id, usage)
        results = await ResultRepository(self._session).list_for_run(project_id, run.id)

        # Reporting pipeline (reused): assemble → DB-state phase → score → classify
        # → rank. DB-state findings (layer=db) land before scoring so they flow
        # through the rest of the pipeline like any other finding.
        await emit(phase=PHASE_REVIEW, step="Review findings", status=STATUS_STARTED)
        await FindingAssembler(self._session, resolver=self._resolver).assemble(
            project_id=project_id, results=results
        )
        # DB-state phase only when the run scope includes the DB layer (ADR-0052);
        # None = full scope, so it runs as before (still tier-gated inside).
        db_in_scope = bounds.layers is None or "db" in bounds.layers
        db_state_report = (
            await self._run_db_state_phase(project_id, run.id, results)
            if db_in_scope
            else None
        )

        scorer = SeverityScorer(self._session, impact_resolver=self._resolver)
        await scorer.score_run(project_id, run.id)
        await HistoryClassifier(self._session).classify_run(project_id, run.id)
        ranked = await scorer.ranked_for_run(project_id, run.id)
        await emit(
            phase=PHASE_REVIEW,
            step="Review complete",
            status=STATUS_PASSED,
            detail={"findings": len(ranked)},
        )

        report = ModeBRunReport(
            run_id=run.id,
            strategy=requested_kind,
            full_sweep_fallback=full_sweep_fallback,
            targets_selected=len(targets),
            cases_generated=generated,
            cases_reused=len(ensured) - generated,
            status=run.status,
            ranked_findings=tuple(ranked),
            db_state=db_state_report,
        )
        logger.info(
            "modes.mode_b.completed",
            extra={
                "project_id": str(project_id),
                "run_id": str(run.id),
                "strategy": requested_kind.value,
                "full_sweep_fallback": full_sweep_fallback,
                "targets": report.targets_selected,
                "generated": report.cases_generated,
                "reused": report.cases_reused,
                "findings": len(ranked),
            },
        )
        # Terminal run event — ends the live stream (best-effort; ADR-0050).
        await emit(
            phase=PHASE_RUN,
            step="run",
            status=STATUS_PASSED if run.status == RUN_STATUS_PASSED else STATUS_FAILED,
            detail={"status": run.status, "findings": len(ranked)},
        )
        return report

    async def _flush_usage(
        self, project_id: uuid.UUID, run_id: uuid.UUID, usage: UsageCollector
    ) -> None:
        """Persist the run's buffered AI usage; best-effort — NEVER break the run.

        The write runs in a SAVEPOINT so a failure rolls back only the usage insert
        and leaves the run's own transaction (findings/score/classify, then the
        caller's commit) intact — usage capture must never poison the session.
        """
        if not usage.records:
            return
        try:
            async with self._session.begin_nested():
                await AiUsageRepository(self._session).add_all(
                    AiUsage(
                        project_id=project_id,
                        run_id=run_id,
                        phase=record.phase,
                        model=record.usage.model,
                        input_tokens=record.usage.input_tokens,
                        output_tokens=record.usage.output_tokens,
                        cache_creation_input_tokens=(
                            record.usage.cache_creation_input_tokens
                        ),
                        cache_read_input_tokens=record.usage.cache_read_input_tokens,
                        total_cost_usd=record.usage.total_cost_usd,
                        model_cost_usd=record.usage.model_cost_usd,
                        usage_available=record.usage.available,
                        is_error=record.usage.is_error,
                    )
                    for record in usage.records
                )
        except Exception:  # noqa: BLE001 — usage capture must never crash a run
            logger.exception(
                "modes.mode_b.usage_flush_failed",
                extra={"project_id": str(project_id), "run_id": str(run_id)},
            )

    async def _run_db_state_phase(
        self,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        results: Sequence[Result],
    ) -> DbStatePhaseReport | None:
        """Run the DB-state phase if wired; NEVER let it crash the run (defensive).

        The safety gate lives inside the phase (it refuses + reports for a prod/
        unflagged target); this outer guard catches anything unexpected so the run's
        own findings/score/classify pipeline is unaffected no matter what.
        """
        if self._db_state is None:
            return None
        try:
            return await self._db_state.run(
                project_id=project_id,
                run_id=run_id,
                target_env_db_url=self._target_env.execution_db.url,
                target_db_ephemeral=self._target_env.execution_db.ephemeral,
                results=results,
            )
        except Exception:  # noqa: BLE001 — DB-state must never crash the rest of a run
            logger.exception(
                "modes.mode_b.db_state_phase_failed",
                extra={"project_id": str(project_id), "run_id": str(run_id)},
            )
            return None

    async def _ensure_cases(
        self,
        project_id: uuid.UUID,
        targets: Sequence[Target],
        bounds: ModeBBounds,
    ) -> list[EnsuredCase]:
        """Reuse-or-generate a runnable case per target, within the time budget."""
        ensured: list[EnsuredCase] = []
        start = self._clock()
        for target in targets:
            if (
                bounds.max_seconds is not None
                and (self._clock() - start) >= bounds.max_seconds
            ):
                logger.info(
                    "modes.mode_b.time_bound_reached",
                    extra={"project_id": str(project_id), "processed": len(ensured)},
                )
                break
            ensured.extend(await self._ensure_for_target(project_id, target))
            # Run-durability: commit each target's case+script the moment it is
            # generated, so a crash on a later target loses only the in-flight item —
            # the cases produced so far are durable (and a re-run reuses them via the
            # never-clobber ``_reuse_scripts`` path). Safe under expire_on_commit=False.
            await self._session.commit()
        return ensured

    async def _ensure_for_target(
        self, project_id: uuid.UUID, target: Target
    ) -> list[EnsuredCase]:
        step = f"{target.kind.value} {target.node_id}"
        detail = {"kind": target.kind.value, "node_id": str(target.node_id)}
        reused = await self._reuse_scripts(project_id, target)
        if reused:  # never regenerate over an existing case (never-clobber)
            # Reuse is part of the journey too — surfaced as a skipped generate step.
            await emit(
                phase=PHASE_GENERATE,
                step=f"Reuse existing test for {step}",
                status=STATUS_SKIPPED,
                detail=detail,
            )
            return [EnsuredCase(script=script, generated=False) for script in reused]
        await emit(
            phase=PHASE_GENERATE,
            step=f"Generate test for {step}",
            status=STATUS_STARTED,
            detail=detail,
        )
        generated = await self._generator.generate(project_id=project_id, target=target)
        await emit(
            phase=PHASE_GENERATE,
            step=f"Generate test for {step}",
            status=STATUS_PASSED,
            detail=detail,
        )
        return [EnsuredCase(script=generated, generated=True)]

    async def _reuse_scripts(
        self, project_id: uuid.UUID, target: Target
    ) -> list[PestScript]:
        """Runnable scripts for the target's existing current cases (deterministic)."""
        cases = await self._cases.list_current_by_target_nodes(
            project_id, {target.node_id}
        )
        scripts: list[PestScript] = []
        for case in cases:
            case_scripts = await self._scripts.list_for_test_case(project_id, case.id)
            if not case_scripts:
                continue  # case with no script yet → not runnable, fall through
            script = case_scripts[0]
            scripts.append(
                PestScript(
                    test_case_id=case.id,
                    script_id=script.id,
                    name=f"reuse-{case.id.hex[:12]}",
                    code=script.code,
                )
            )
        return scripts
