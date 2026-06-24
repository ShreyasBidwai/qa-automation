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

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.types import AIProvider
from app.core.config import Settings
from app.documents.grounding import SpecGroundingService
from app.embeddings.types import EmbeddingProvider
from app.execution.php_test_runner import PhpTestRunner
from app.execution.playwright_runner import PlaywrightRunner
from app.execution.types import DbHandle, DbRole, ExecutionRunner, PestScript, TargetEnv
from app.generation.e2e_generator import E2EGenerator
from app.generation.generator import TestGenerator
from app.ingestion.laravel.ingester import LaravelIngester
from app.ingestion.laravel.route_list import path_params_from_uri
from app.ingestion.models import (
    EndpointSpec,
    FieldConstraints,
    RelationalRule,
    ValidationField,
)
from app.models.enums import NodeKind
from app.models.model_node import ModelNode
from app.modes.selection import Target
from app.repositories.node_repository import NodeRepository
from app.repositories.project_repository import ProjectRepository

from .errors import ApiConfigError
from .project_target import ResolvedTargetConfig, resolve_target_config


class TargetGenerationError(Exception):
    """A target could not be turned into a runnable case (unknown node / kind)."""


# --- EndpointSpec ⟵ Brain node ----------------------------------------------


def _validation_field(data: dict[str, Any]) -> ValidationField:
    constraints = data.get("constraints") or {}
    relational = data.get("relational")
    return ValidationField(
        name=str(data.get("name", "")),
        raw_rules=list(data.get("raw_rules", [])),
        required=bool(data.get("required", False)),
        type=str(data.get("type", "unknown")),
        constraints=FieldConstraints(
            min=constraints.get("min"),
            max=constraints.get("max"),
            size=constraints.get("size"),
        ),
        relational=(
            RelationalRule(
                kind=relational["kind"],
                table=relational["table"],
                column=relational.get("column"),
            )
            if relational
            else None
        ),
    )


def endpoint_spec_from_node(node: ModelNode) -> EndpointSpec:
    """Rebuild the generator's ``EndpointSpec`` from an endpoint node's attributes.

    The Laravel ingestor stores method/uri/auth + the captured validation spec on
    the node (``ingester.py``); this is its inverse so the backend generator can run
    off the Brain without re-reading the repo.
    """
    attrs = node.attributes or {}
    uri = str(attrs.get("uri", ""))
    validation = attrs.get("validation") or {}
    return EndpointSpec(
        method=str(attrs.get("method", "GET")),
        uri=uri,
        route_name=attrs.get("name"),
        auth_required=bool(attrs.get("auth_required", False)),
        path_params=path_params_from_uri(uri),
        query_params=[],
        validation_fields=[_validation_field(f) for f in validation.get("fields", [])],
    )


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


class LaravelIngestorAdapter:
    """Real Laravel ingestion behind the ``Ingestor`` port (ingest → Brain).

    Reads the repo location FROM THE PROJECT (ADR-0054) — ``repo_url`` on the project,
    with ``TARGET_REPO_PATH`` only as a deprecated env fallback — and builds the Brain
    via ``LaravelIngester``. (Per-project git checkout from a git URL is the next step;
    today the resolved repo is a local path.)
    """

    def __init__(
        self, *, settings: Settings, embedding_provider: EmbeddingProvider
    ) -> None:
        self._settings = settings
        self._ingester = LaravelIngester(embedding_provider=embedding_provider)

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

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def resolve(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> tuple[ExecutionRunner, TargetEnv]:
        project = await ProjectRepository(session).get(project_id)
        if project is None:
            raise ApiConfigError(f"project {project_id} not found for target config")
        cfg = resolve_target_config(project, self._settings)
        return build_runner_for(cfg), build_target_env_for(cfg, self._settings)
