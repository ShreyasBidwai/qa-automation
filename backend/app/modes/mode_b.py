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

from app.brain.cross_layer import Impact, Subgraph
from app.execution.lifecycle import RunLifecycle
from app.execution.types import ExecutionRunner, PestScript, TargetEnv
from app.models.enums import RunMode, RunTrigger
from app.models.finding import Finding
from app.reporting import FindingAssembler, HistoryClassifier, SeverityScorer
from app.repositories.result_repository import ResultRepository
from app.repositories.test_case_repository import TestCaseRepository
from app.repositories.test_script_repository import TestScriptRepository

from .selection import (
    FullSweepStrategy,
    SelectionStrategy,
    SelectionStrategyKind,
    Target,
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
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session = session
        self._runner = runner
        self._target_env = target_env
        self._resolver = resolver
        self._generator = generator
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
        """Select → ensure → execute → report, autonomously (deterministic, scoped)."""
        requested_kind = strategy.kind
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

        targets = selection.targets[: bounds.max_targets]  # hard count bound
        ensured = await self._ensure_cases(project_id, targets, bounds)
        scripts = [e.script for e in ensured]
        generated = sum(1 for e in ensured if e.generated)

        run = await RunLifecycle(runner=self._runner).execute(
            session=self._session,
            project_id=project_id,
            scripts=scripts,
            target_env=self._target_env,
            trigger=_trigger_for(requested_kind),
            mode=RunMode.B,
        )
        results = await ResultRepository(self._session).list_for_run(project_id, run.id)

        # Reporting pipeline (reused): assemble → score → classify → rank.
        await FindingAssembler(self._session, resolver=self._resolver).assemble(
            project_id=project_id, results=results
        )
        scorer = SeverityScorer(self._session, impact_resolver=self._resolver)
        await scorer.score_run(project_id, run.id)
        await HistoryClassifier(self._session).classify_run(project_id, run.id)
        ranked = await scorer.ranked_for_run(project_id, run.id)

        report = ModeBRunReport(
            run_id=run.id,
            strategy=requested_kind,
            full_sweep_fallback=full_sweep_fallback,
            targets_selected=len(targets),
            cases_generated=generated,
            cases_reused=len(ensured) - generated,
            status=run.status,
            ranked_findings=tuple(ranked),
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
        return report

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
        return ensured

    async def _ensure_for_target(
        self, project_id: uuid.UUID, target: Target
    ) -> list[EnsuredCase]:
        reused = await self._reuse_scripts(project_id, target)
        if reused:  # never regenerate over an existing case (never-clobber)
            return [EnsuredCase(script=script, generated=False) for script in reused]
        generated = await self._generator.generate(project_id=project_id, target=target)
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
