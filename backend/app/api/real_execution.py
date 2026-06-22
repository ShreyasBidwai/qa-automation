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
    port (reads a checked-out repo path; builds the Brain).
  - ``build_runner`` / ``build_target_env`` — the per-stack runner + the target
    environment from settings.

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
from app.embeddings.types import EmbeddingProvider
from app.execution.pest_runner import PestRunner
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

from .errors import ApiConfigError


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
    ) -> None:
        self._session = session
        self._nodes = NodeRepository(session)
        self._endpoint_gen = TestGenerator(
            provider=ai_provider,
            budget_tokens=budget_tokens,
            generated_by=generated_by,
            factories_available=factories_available,
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

    Reads a checked-out repo path (``target_repo_path``) and builds the Brain via
    ``LaravelIngester``. (Per-project git checkout from the project's repo_url is the
    next step; for the bridge + smoke the repo is a configured local path.)
    """

    def __init__(
        self, *, repo_path: str, embedding_provider: EmbeddingProvider
    ) -> None:
        self._repo_path = repo_path
        self._ingester = LaravelIngester(embedding_provider=embedding_provider)

    async def ingest(
        self, *, session: AsyncSession, project_id: uuid.UUID
    ) -> dict[str, Any]:
        if not self._repo_path:
            raise ApiConfigError(
                "ingestor_mode=laravel requires TARGET_REPO_PATH (the Laravel repo)"
            )
        result = await self._ingester.ingest(
            session=session, project_id=project_id, repo_path=self._repo_path
        )
        return {
            "mode": "laravel",
            "source_sha": result.source_sha,
            "nodes": result.nodes,
            "edges": result.edges,
        }


# --- per-stack runner + target environment from settings ---------------------


def build_runner(settings: Settings) -> ExecutionRunner:
    if settings.runner_framework == "pest":
        return PestRunner()
    if settings.runner_framework == "playwright":
        return PlaywrightRunner(node_project_dir=settings.target_app_path or ".")
    raise ApiConfigError(
        f"unknown runner_framework {settings.runner_framework!r} "
        "(expected 'pest' or 'playwright')"
    )


def build_target_env(settings: Settings) -> TargetEnv:
    return TargetEnv(
        app_path=settings.target_app_path,
        execution_db=DbHandle(
            settings.execution_db_url, DbRole.WRITABLE_TEST, ephemeral=True
        ),
        evidence_dir=settings.evidence_dir,
        base_url=settings.target_base_url,
    )
