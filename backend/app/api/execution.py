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
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.types import AIProvider
from app.credentials import resolve_target_login
from app.db_state.run_phase import DbStateRunPhase, EngineTargetConnector
from app.embeddings.types import EmbeddingProvider
from app.execution.types import ExecutionRunner, TargetEnv
from app.impact.selector import ChangeSet
from app.models.enums import CredentialMode, RunMode
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


class TargetProvider(Protocol):
    """Resolves a run's (runner, TargetEnv) per project (ADR-0054). The production
    impl reads the Project record; tests inject a fixed one."""

    async def resolve(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> tuple[ExecutionRunner, TargetEnv]: ...


class AIProviderResolver(Protocol):
    """Resolves a run's AIProvider per project (the UI provider choice). The
    production impl reads ``project.settings['ai_provider']``; absent ⇒ this is None
    and the executor uses its fixed ``ai_provider`` (tests/stub)."""

    async def resolve(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> AIProvider: ...


class OrchestratorRunExecutor:
    """The production RunExecutor: dispatches to Mode B / Mode C orchestrators."""

    def __init__(
        self,
        *,
        runner: ExecutionRunner | None = None,
        target_env: TargetEnv | None = None,
        target_provider: TargetProvider | None = None,
        resolver_factory: Callable[[AsyncSession], BrainResolver],
        target_generator_factory: Callable[[AsyncSession, AIProvider], TargetGenerator],
        ai_provider: AIProvider | None = None,
        ai_provider_resolver: AIProviderResolver | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        # Either a per-project ``target_provider`` (production — reads target config
        # from the Project, ADR-0054) OR a fixed runner+target_env (tests/stub).
        self._runner = runner
        self._target_env = target_env
        self._target_provider = target_provider
        # Resolver + generator are SESSION-scoped (the resolver wraps a session, the
        # generator persists through it), so they're built per-execute from the
        # job's session — not held as singletons (the prior B5 gap).
        self._resolver_factory = resolver_factory
        self._generator_factory = target_generator_factory
        self._ai = ai_provider
        # Per-project provider choice (the UI toggle); None ⇒ use the fixed ``_ai``.
        self._ai_resolver = ai_provider_resolver
        self._embed = embedding_provider

    async def _resolve_ai_provider(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> AIProvider:
        """The run's AIProvider — resolved PER PROJECT when a resolver is wired (the
        UI provider choice), else the fixed ``ai_provider`` (tests/stub)."""
        if self._ai_resolver is not None:
            return await self._ai_resolver.resolve(session, project_id)
        if self._ai is not None:
            return self._ai
        raise ApiConfigError(
            "run executor needs an ai_provider_resolver or a fixed ai_provider"
        )

    async def _resolve_target(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> tuple[ExecutionRunner, TargetEnv]:
        """The run's runner + TargetEnv — resolved PER PROJECT when a provider is
        wired (ADR-0054), else the fixed pair (tests/stub)."""
        if self._target_provider is not None:
            return await self._target_provider.resolve(session, project_id)
        if self._runner is not None and self._target_env is not None:
            return self._runner, self._target_env
        raise ApiConfigError(
            "run executor needs a target_provider or a runner + target_env"
        )

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
        # Target-account selection (ADR-0053): a specific-account project authenticates
        # as the user-provided account; otherwise Polaris provisions its own (existing
        # behaviour). ``resolve_target_login`` is the ONLY place the secret is
        # decrypted (in memory); the secret is never put in the summary, logs, or
        # events — only the chosen mode is. (Actual target-auth is stubbed: T4.2a is
        # not yet wired into runs; a real run hands the login to the AuthStrategy.)
        target_login = await resolve_target_login(session, project_id)
        auth_mode = (
            CredentialMode.SPECIFIC_ACCOUNT.value
            if target_login is not None
            else CredentialMode.POLARIS_CREATES.value
        )
        # Target config (runner + where/what to test) comes FROM THE PROJECT when a
        # provider is wired (ADR-0054), not from instance env.
        runner, target_env = await self._resolve_target(session, project_id)
        # The AI backend is the project's choice (claude_cli | gemini), resolved here.
        ai_provider = await self._resolve_ai_provider(session, project_id)
        resolver = self._resolver_factory(session)
        generator = self._generator_factory(session, ai_provider)
        strategy = build_selection_strategy(
            request.strategy or SelectionStrategyKind.FULL_SWEEP,
            session=session,
            resolver=resolver,
            changeset=ChangeSet.of(request.changeset),
        )
        orchestrator = ModeBOrchestrator(
            session=session,
            runner=runner,
            target_env=target_env,
            resolver=resolver,
            generator=generator,
            # DB-state phase (B11, ADR-0044): tier-gated per project (off → no-op),
            # gate-enforced for writes. Asserts against the run's target DB by URL;
            # off projects (the default) never reach the connector.
            db_state=DbStateRunPhase(
                session,
                resolver=resolver,
                connector=EngineTargetConnector(target_env.execution_db.url),
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
            # The account-provisioning decision (never the secret) — ADR-0053.
            "auth_mode": auth_mode,
        }
        return RunExecution(run_id=report.run_id, summary=summary)

    async def _run_mode_c(
        self, session: AsyncSession, project_id: uuid.UUID, request: RunRequest
    ) -> RunExecution:
        if self._embed is None:
            raise ApiConfigError(
                "mode_c execution requires an embedding provider to be composed"
            )
        ai_provider = await self._resolve_ai_provider(session, project_id)
        orchestrator = build_mode_c_orchestrator(
            session, ai_provider=ai_provider, embedding_provider=self._embed
        )
        result = await orchestrator.propose(
            project_id=project_id, nl=request.prompt or ""
        )
        # Authoring produces proposed cases, not a run/findings (run_id is None).
        return RunExecution(
            run_id=None,
            summary={"mode": "mode_c", "proposed_cases": len(result.cases)},
        )
