"""Real-execution collaborators for orchestrator mode (the B5→B6 bridge).

B5 shipped the decoupled topology but flagged the orchestrator executor's
collaborators as not production-wired: the session-scoped Brain resolver and the
AI-backed target generator. This module supplies the real wiring so
``build_run_executor(orchestrator)`` returns a FULLY-WIRED executor:

  - ``OrchestratorTargetGenerator`` — the production ``TargetGenerator``: an
    endpoint target dispatches to the deterministic-plan + AI-rendered backend
    generator (``TestGenerator``), a page target to the E2E generator
    (``E2EGenerator``); both persist through the never-clobber merge engine. It is
    session-scoped (built per run from the job's session).
  - ``endpoint_spec_from_node`` — rebuild the ``EndpointSpec`` the backend
    generator needs from the Brain endpoint node's captured attributes.
  - ``LaravelIngestorAdapter`` — the real Laravel ingestor behind the ``Ingestor``
    port (reads the repo from the Project; builds the Brain).
  - ``ProjectTargetProvider`` / ``build_runner_for`` / ``build_target_env_for`` — the
    per-PROJECT runner + target environment, resolved from the Project record at run
    time (ADR-0054), with env as a deprecated fallback.

The AI/embedding providers are composed from the factories, so the generator is
"AI-backed" structurally; which provider it holds (stub vs claude_cli) is config —
the hermetic suite uses the stub, the manual smoke a real model.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Protocol
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.factory import build_ai_provider
from app.ai.types import AIProvider
from app.core.config import Settings
from app.documents.grounding import SpecGroundingService
from app.embeddings.types import EmbeddingProvider
from app.execution.php_test_runner import PhpTestRunner
from app.execution.playwright_runner import PlaywrightRunner
from app.execution.provision import TargetAppProvisioner
from app.execution.types import DbHandle, DbRole, ExecutionRunner, PestScript, TargetEnv
from app.generation.e2e_generator import E2EGenerator

# Re-exported for backward compatibility — the Brain-node→EndpointSpec inverse moved
# to app.generation.endpoint_from_node so NL-authoring can reuse it without an
# api⇄modes import cycle. Existing callers still import it from here.
from app.generation.endpoint_from_node import endpoint_spec_from_node
from app.generation.generator import TestGenerator
from app.git.cli import GitCliProvider
from app.git.types import GitProvider
from app.incidents import capturing_ai_provider
from app.ingestion.git_ingest import ingest_from_git
from app.ingestion.laravel.ingester import LaravelIngester
from app.models.enums import NodeKind
from app.modes.selection import Target
from app.repositories.node_repository import NodeRepository
from app.repositories.project_repository import ProjectRepository

from .errors import ApiConfigError
from .project_target import (
    ResolvedTargetConfig,
    resolve_ai_provider_mode,
    resolve_target_config,
)


class TargetGenerationError(Exception):
    """A target could not be turned into a runnable case (unknown node / kind)."""


# --- the production TargetGenerator ------------------------------------------


class _GeneratedLike(Protocol):
    """The shared shape of an endpoint/page generated case (both carry these)."""

    test_case: Any
    test_script: Any


def _first_script(cases: Sequence[_GeneratedLike], target: Target) -> PestScript:
    """One representative runnable script from a generated case set."""
    if not cases:
        raise TargetGenerationError(
            f"generator produced no cases for target {target.node_id}"
        )
    first = cases[0]
    return PestScript(
        test_case_id=first.test_case.id,
        script_id=first.test_script.id,
        name=f"gen-{first.test_case.id.hex[:12]}",
        code=first.test_script.code,
    )


class OrchestratorTargetGenerator:
    """Production ``TargetGenerator`` (modes.mode_b): dispatch per target kind.

    Endpoint → ``TestGenerator`` (deterministic plan, AI-rendered scripts); page →
    ``E2EGenerator`` (cross-layer journey plan, AI-rendered specs). Both persist all
    planned cases via the merge engine; ``generate`` returns one representative
    runnable script per target (the rest are picked up on the next run via the
    never-clobber reuse path). Session-scoped — one per run.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        ai_provider: AIProvider,
        budget_tokens: int,
        generated_by: str = "orchestrator",
        factories_available: bool = True,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._session = session
        self._nodes = NodeRepository(session)
        # Spec-grounding (B9): with an embedding provider, doc-backed cases are
        # upgraded to spec-grounded at generation time.
        grounder = (
            SpecGroundingService(session, embedding_provider=embedding_provider)
            if embedding_provider is not None
            else None
        )
        self._endpoint_gen = TestGenerator(
            provider=ai_provider,
            budget_tokens=budget_tokens,
            generated_by=generated_by,
            factories_available=factories_available,
            grounder=grounder,
        )
        self._page_gen = E2EGenerator(
            provider=ai_provider, budget_tokens=budget_tokens, generated_by=generated_by
        )

    async def generate(self, *, project_id: uuid.UUID, target: Target) -> PestScript:
        if target.kind is NodeKind.ENDPOINT:
            nodes = await self._nodes.get_many(project_id, {target.node_id})
            if not nodes:
                raise TargetGenerationError(f"endpoint node {target.node_id} not found")
            spec = endpoint_spec_from_node(nodes[0])
            return _first_script(
                await self._endpoint_gen.generate_and_persist(
                    session=self._session, project_id=project_id, spec=spec
                ),
                target,
            )
        if target.kind is NodeKind.PAGE:
            return _first_script(
                await self._page_gen.generate_and_persist(
                    session=self._session,
                    project_id=project_id,
                    page_node_id=target.node_id,
                ),
                target,
            )
        raise TargetGenerationError(
            f"unsupported target kind {target.kind.value} for generation"
        )


# --- the real Laravel ingestor behind the Ingestor port ----------------------


# A project's ``repo_url`` is a git remote to clone (read-only) when it carries one
# of these schemes; anything else (``/targets/app``, ``./x``) is an already-present
# local checkout. So an operator can paste a Gitea URL in the UI OR point at a mount.
_GIT_URL_SCHEMES = frozenset({"http", "https", "git", "ssh"})


def _looks_like_git_url(value: str) -> bool:
    return urlsplit(value).scheme in _GIT_URL_SCHEMES


class LaravelIngestorAdapter:
    """Real Laravel ingestion behind the ``Ingestor`` port (ingest → Brain).

    Reads the repo location FROM THE PROJECT (ADR-0054). ``repo_url`` may be a **git
    remote** — cloned READ-ONLY (shallow, into a temp dir, cleaned up; the token is
    injected at fetch time and redacted from every log; there is no push path, ever) —
    OR an already-present local checkout path. Either way the Brain is built by
    ``LaravelIngester`` (static source reading, ADR-0055: no ``vendor/``, no boot).
    """

    def __init__(
        self,
        *,
        settings: Settings,
        embedding_provider: EmbeddingProvider,
        git_provider: GitProvider | None = None,
    ) -> None:
        self._settings = settings
        self._ingester = LaravelIngester(embedding_provider=embedding_provider)
        # Injectable so tests exercise the git path without a real remote; the default
        # is the read-only CLI provider, credentialed from the read-only GIT_TOKEN.
        self._git_provider = git_provider

    def _resolve_git_provider(self) -> GitProvider:
        if self._git_provider is not None:
            return self._git_provider
        return GitCliProvider(
            token=self._settings.git_token,
            token_username=self._settings.git_token_username,
            timeout=self._settings.git_clone_timeout_seconds,
        )

    async def ingest(
        self, *, session: AsyncSession, project_id: uuid.UUID
    ) -> dict[str, Any]:
        project = await ProjectRepository(session).get(project_id)
        if project is None:
            raise ApiConfigError(f"project {project_id} not found for ingestion")
        cfg = resolve_target_config(project, self._settings)
        if not cfg.repo_path:
            raise ApiConfigError(
                "project has no repo configured — set repo_url on the project "
                "(ingestor_mode=laravel needs the Laravel source)"
            )
        # The ref to check out — a project may pin a branch/tag/SHA; default to the
        # remote's default branch.
        ref = str((project.settings or {}).get("repo_ref") or "HEAD")
        if _looks_like_git_url(cfg.repo_path):
            result = await ingest_from_git(
                session=session,
                project_id=project_id,
                repo_url=cfg.repo_path,
                ref=ref,
                provider=self._resolve_git_provider(),
                ingester=self._ingester,
            )
        else:
            result = await self._ingester.ingest(
                session=session, project_id=project_id, repo_path=cfg.repo_path
            )
        return {
            "mode": "laravel",
            "source_sha": result.source_sha,
            "nodes": result.nodes,
            "edges": result.edges,
        }


# --- per-project runner + target environment (resolved from the Project) ------


def build_runner_for(cfg: ResolvedTargetConfig) -> ExecutionRunner:
    """The execution runner for a project's resolved framework (ADR-0054)."""
    if cfg.framework == "pest":
        return PhpTestRunner()
    if cfg.framework == "playwright":
        if not cfg.base_url:
            # A browser run needs the running app; fail clearly at run start.
            raise ApiConfigError(
                "project has no target base URL configured — set app_url on the "
                "project (a browser run needs the running app)"
            )
        return PlaywrightRunner(node_project_dir=cfg.app_path or ".")
    raise ApiConfigError(
        f"unknown framework {cfg.framework!r} (expected 'pest' or 'playwright')"
    )


def build_target_env_for(cfg: ResolvedTargetConfig, settings: Settings) -> TargetEnv:
    """A run's TargetEnv: app-level fields from the PROJECT (ADR-0054); the disposable
    execution DB + evidence dir stay infra (env)."""
    return TargetEnv(
        app_path=cfg.app_path,
        execution_db=DbHandle(
            settings.execution_db_url, DbRole.WRITABLE_TEST, ephemeral=True
        ),
        evidence_dir=settings.evidence_dir,
        base_url=cfg.base_url,
    )


class ProjectTargetProvider:
    """Resolves a run's (runner, TargetEnv) PER PROJECT (ADR-0054).

    The executor calls this with the run's session + project so a run reads its target
    config from the Project record, not from instance env. Project wins; env is a
    deprecated fallback (logged in ``resolve_target_config``).
    """

    def __init__(
        self, settings: Settings, *, provisioner: TargetAppProvisioner | None = None
    ) -> None:
        self._settings = settings
        # Injectable so tests exercise resolve() without a real git/composer; the
        # default is built lazily (only when provisioning is actually needed).
        self._provisioner = provisioner

    def _resolve_provisioner(self) -> TargetAppProvisioner:
        if self._provisioner is not None:
            return self._provisioner
        git = GitCliProvider(
            token=self._settings.git_token,
            token_username=self._settings.git_token_username,
            timeout=self._settings.git_clone_timeout_seconds,
        )
        return TargetAppProvisioner(
            git_sync=git,
            composer_timeout=self._settings.composer_install_timeout_seconds,
        )

    async def resolve(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> tuple[ExecutionRunner, TargetEnv]:
        project = await ProjectRepository(session).get(project_id)
        if project is None:
            raise ApiConfigError(f"project {project_id} not found for target config")
        cfg = resolve_target_config(project, self._settings)
        # Auto-provision the PHP checkout so the API/Pest layer runs without a manual
        # `composer install` (ADR-0074). Best-effort: a failure leaves app_path as-is
        # and the run degrades to the graceful "skip API layer" path (lifecycle.py).
        if self._settings.target_provision_enabled:
            ref = str((project.settings or {}).get("repo_ref") or "HEAD")
            self._resolve_provisioner().ensure_php_checkout(
                repo_path=cfg.repo_path,
                app_path=cfg.app_path,
                framework=cfg.framework,
                ref=ref,
            )
        return build_runner_for(cfg), build_target_env_for(cfg, self._settings)


class ProjectAIProvider:
    """Resolves a run's ``AIProvider`` PER PROJECT — the UI provider choice.

    The executor calls this with the run's session + project so generation uses the
    backend the project picked (``project.settings['ai_provider']`` → claude_cli or
    gemini), falling back to the instance default. The built provider is wrapped so a
    provider failure is tagged + captured as ``provider`` (ADR-0047), matching the
    prior global wiring. The stored mode is allow-listed in ``resolve_ai_provider_mode``
    before it reaches the factory.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def resolve(self, session: AsyncSession, project_id: uuid.UUID) -> AIProvider:
        project = await ProjectRepository(session).get(project_id)
        if project is None:
            raise ApiConfigError(f"project {project_id} not found for AI provider")
        mode = resolve_ai_provider_mode(project, self._settings)
        return capturing_ai_provider(build_ai_provider(self._settings, mode=mode))
