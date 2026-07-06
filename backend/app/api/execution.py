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
from app.auth.browser import PlaywrightLoginBrowser
from app.auth.otp import autonomous_otp_unavailable
from app.auth.strategy import ManualOtpStrategy, TotpStrategy
from app.auth.types import AuthConfig, AuthStrategy
from app.core.config import get_settings
from app.crawler.crawler import FrontendCrawler
from app.crawler.playwright_fetcher import PlaywrightPageFetcher
from app.credentials import resolve_target_auth_config, resolve_target_login
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
from app.modes.mode_c_api import build_mode_c_api_orchestrator
from app.modes.selection import SelectionStrategyKind, build_selection_strategy

from .errors import ApiConfigError
from .ports import RunExecution, RunRequest


def _build_crawler(
    target_env: TargetEnv, *, auth_config: AuthConfig | None = None
) -> FrontendCrawler | None:
    """A frontend crawler for the run, or None to skip the crawl phase.

    Wired only when ``crawl_driver_dir`` is configured (the Playwright drivers live
    there) AND the project has a frontend ``base_url`` to crawl. Keeps the crawl
    opt-in and infra-gated, exactly like the DB-state phase is tier-gated.

    When ``auth_config`` is present (the project has a target login + login config),
    the crawler is given a real login strategy: it logs in once via the Playwright
    login driver and replays that session on every page, so the crawl reaches
    behind-the-gate journeys. A TOTP secret in the config selects the automated
    TotpStrategy (unattended 2FA); otherwise manual-OTP semantics. No config ⇒
    unauthenticated (the default).
    """
    settings = get_settings()
    driver_dir = settings.crawl_driver_dir
    if not driver_dir or not target_env.base_url:
        return None
    fetcher = PlaywrightPageFetcher(
        base_url=target_env.base_url,
        node_project_dir=driver_dir,
        interact=settings.crawl_interactions_enabled,
        max_interactions=settings.crawl_max_interactions,
    )
    auth_strategy = (
        _build_auth_strategy(driver_dir, use_totp=bool(auth_config.totp_secret))
        if auth_config is not None
        else None
    )
    return FrontendCrawler(fetcher, auth_strategy=auth_strategy)


def _build_auth_strategy(driver_dir: str, *, use_totp: bool) -> AuthStrategy:
    """A login strategy that drives the real Playwright login driver.

    With a TOTP secret configured, the automated TotpStrategy generates the 2FA code
    (pyotp) so the login completes unattended. Otherwise manual-OTP semantics with an
    autonomous OtpProvider: a plain form login completes headless; an unexpected OTP
    challenge fails fast (no operator) and the crawl phase degrades to an
    unauthenticated crawl rather than hanging. Credentials go over stdin, never argv.
    """
    browser = PlaywrightLoginBrowser(node_project_dir=driver_dir)
    if use_totp:
        return TotpStrategy(browser=browser)
    return ManualOtpStrategy(browser=browser, otp_provider=autonomous_otp_unavailable)


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
        # events — only the chosen mode is.
        target_login = await resolve_target_login(session, project_id)
        auth_mode = (
            CredentialMode.SPECIFIC_ACCOUNT.value
            if target_login is not None
            else CredentialMode.POLARIS_CREATES.value
        )
        # The crawl logs in + reaches behind-the-gate pages when the project has BOTH a
        # specific-account credential AND a login config (settings['auth_config']); the
        # secret lives only inside this AuthConfig (its repr masks it) and is replayed
        # via the AuthStrategy. Absent ⇒ the crawl stays unauthenticated (as before).
        auth_config = await resolve_target_auth_config(session, project_id)
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
            # Frontend crawl phase (T4.2): wired only when a crawl driver dir is
            # configured AND the project has a frontend URL. One run then covers
            # backend + DB + frontend; otherwise the phase is simply skipped. With a
            # login config present, the crawler authenticates to reach gated pages.
            crawler=_build_crawler(target_env, auth_config=auth_config),
            # The login config the crawl authenticates with (None ⇒ unauthenticated);
            # its secret is masked and never logged/summarised.
            auth_config=auth_config,
            # The project's AI backend also triages failures (real-bug vs noise); the
            # cheap tier (ai_triage_model) keeps it inexpensive (ADR-0049).
            ai_provider=ai_provider,
        )
        report = await orchestrator.run(
            project_id=project_id,
            strategy=strategy,
            bounds=ModeBBounds(
                max_targets=request.max_targets,
                layers=request.layers,
                modules=request.modules,
            ),
        )
        counts = report.outcome_counts
        # Verified = pass + fail + error; SKIPPED (reachable-but-unverified) is excluded
        # so a passing run isn't dragged down, and an all-skipped module has no rate
        # rather than a misleading 0% (ADR-0064). Mirrors project_summary.pass_rate.
        verified = counts["pass"] + counts["fail"] + counts["error"]
        summary: dict[str, Any] = {
            "mode": "mode_b",
            "strategy": report.strategy.value,
            "full_sweep_fallback": report.full_sweep_fallback,
            "targets_selected": report.targets_selected,
            "cases_generated": report.cases_generated,
            "cases_reused": report.cases_reused,
            "status": report.status,
            "findings": len(report.ranked_findings),
            # The run's outcome breakdown, so the dashboard self-explains (ADR-0064).
            "tests": sum(counts.values()),
            "passed": counts["pass"],
            "failed": counts["fail"],
            "errors": counts["error"],
            "skipped": counts["skipped"],
            "pass_rate": (round(counts["pass"] / verified, 4) if verified else None),
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
        # ``layer`` picks the authoring engine: "api" resolves the described endpoint
        # and authors its contract tests; "ui" (default) composes a browser journey.
        if request.layer == "api":
            api_orchestrator = build_mode_c_api_orchestrator(
                session, ai_provider=ai_provider, embedding_provider=self._embed
            )
            api_result = await api_orchestrator.propose(
                project_id=project_id, nl=request.prompt or ""
            )
            return RunExecution(
                run_id=None,
                summary={
                    "mode": "mode_c",
                    "layer": "api",
                    "endpoint": api_result.endpoint.name,
                    "proposed_cases": len(api_result.cases),
                },
            )
        orchestrator = build_mode_c_orchestrator(
            session, ai_provider=ai_provider, embedding_provider=self._embed
        )
        result = await orchestrator.propose(
            project_id=project_id, nl=request.prompt or ""
        )
        # Authoring produces proposed cases, not a run/findings (run_id is None).
        return RunExecution(
            run_id=None,
            summary={
                "mode": "mode_c",
                "layer": "ui",
                "proposed_cases": len(result.cases),
            },
        )
