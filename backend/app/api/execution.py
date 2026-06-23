"""Reference RunExecutor — wires the API to the existing orchestrators (ADR-0026).

Reuse, not reimplement: ``mode_b`` dispatches to ``ModeBOrchestrator.run`` (with a
strategy from ``build_selection_strategy``) and ``mode_c`` to the Mode C
orchestrator. Heavy collaborators (runner, resolver, generator, AI/embedding) are
injected at composition; the API boots without them and only this executor needs
them — so the fast lane can stub the ``RunExecutor`` port entirely.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.types import AIProvider
from app.db_state.run_phase import DbStateRunPhase, EngineTargetConnector
from app.embeddings.types import EmbeddingProvider
from app.execution.types import ExecutionRunner, TargetEnv
from app.impact.selector import ChangeSet
from app.models.enums import RunMode
from app.modes.mode_b import (
    BrainResolver,
    ModeBBounds,
    ModeBOrchestrator,
    TargetGenerator,
)
from app.modes.mode_c import build_mode_c_orchestrator
from app.modes.selection import SelectionStrategyKind, build_selection_strategy

from .errors import ApiConfigError
from .ports import RunExecution, RunRequest


class OrchestratorRunExecutor:
    """The production RunExecutor: dispatches to Mode B / Mode C orchestrators."""

    def __init__(
        self,
        *,
        runner: ExecutionRunner,
        target_env: TargetEnv,
        resolver_factory: Callable[[AsyncSession], BrainResolver],
        target_generator_factory: Callable[[AsyncSession], TargetGenerator],
        ai_provider: AIProvider | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._runner = runner
        self._target_env = target_env
        # Resolver + generator are SESSION-scoped (the resolver wraps a session, the
        # generator persists through it), so they're built per-execute from the
        # job's session — not held as singletons (the prior B5 gap).
        self._resolver_factory = resolver_factory
        self._generator_factory = target_generator_factory
        self._ai = ai_provider
        self._embed = embedding_provider

    async def execute(
        self,
        *,
        session: AsyncSession,
        project_id: uuid.UUID,
        request: RunRequest,
    ) -> RunExecution:
        if request.mode is RunMode.B:
            return await self._run_mode_b(session, project_id, request)
        return await self._run_mode_c(session, project_id, request)

    async def _run_mode_b(
        self, session: AsyncSession, project_id: uuid.UUID, request: RunRequest
    ) -> RunExecution:
        resolver = self._resolver_factory(session)
        generator = self._generator_factory(session)
        strategy = build_selection_strategy(
            request.strategy or SelectionStrategyKind.FULL_SWEEP,
            session=session,
            resolver=resolver,
            changeset=ChangeSet.of(request.changeset),
        )
        orchestrator = ModeBOrchestrator(
            session=session,
            runner=self._runner,
            target_env=self._target_env,
            resolver=resolver,
            generator=generator,
            # DB-state phase (B11, ADR-0044): tier-gated per project (off → no-op),
            # gate-enforced for writes. Asserts against the run's target DB by URL;
            # off projects (the default) never reach the connector.
            db_state=DbStateRunPhase(
                session,
                resolver=resolver,
                connector=EngineTargetConnector(self._target_env.execution_db.url),
            ),
        )
        report = await orchestrator.run(
            project_id=project_id,
            strategy=strategy,
            bounds=ModeBBounds(max_targets=request.max_targets, layers=request.layers),
        )
        summary: dict[str, Any] = {
            "mode": "mode_b",
            "strategy": report.strategy.value,
            "full_sweep_fallback": report.full_sweep_fallback,
            "targets_selected": report.targets_selected,
            "cases_generated": report.cases_generated,
            "cases_reused": report.cases_reused,
            "status": report.status,
            "findings": len(report.ranked_findings),
        }
        return RunExecution(run_id=report.run_id, summary=summary)

    async def _run_mode_c(
        self, session: AsyncSession, project_id: uuid.UUID, request: RunRequest
    ) -> RunExecution:
        if self._ai is None or self._embed is None:
            raise ApiConfigError(
                "mode_c execution requires AI + embedding providers to be composed"
            )
        orchestrator = build_mode_c_orchestrator(
            session, ai_provider=self._ai, embedding_provider=self._embed
        )
        result = await orchestrator.propose(
            project_id=project_id, nl=request.prompt or ""
        )
        # Authoring produces proposed cases, not a run/findings (run_id is None).
        return RunExecution(
            run_id=None,
            summary={"mode": "mode_c", "proposed_cases": len(result.cases)},
        )
