"""Orchestrator-mode composition is FULLY wired (B5→B6 bridge), validated
structurally — NO live model call.

The hermetic proof for "wire the real execution path": with stub AI/embedding
(so the suite never calls a live model), ``build_run_executor('orchestrator')``
yields a real ``OrchestratorRunExecutor`` whose collaborators are all present and of
the real production types — including the two B5 flagged as missing: the
session-scoped Brain resolver and the AI-backed target generator. Plus the
``EndpointSpec``-from-node reconstruction the generator relies on.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.stub import StubAIProvider
from app.api.composition import build_ingestor, build_run_executor
from app.api.execution import OrchestratorRunExecutor
from app.api.real_execution import (
    LaravelIngestorAdapter,
    OrchestratorTargetGenerator,
    ProjectTargetProvider,
    endpoint_spec_from_node,
)
from app.brain.cross_layer import CrossLayerResolver
from app.core.config import Settings
from app.embeddings.stub import StubEmbeddingProvider
from app.generation.e2e_generator import E2EGenerator
from app.generation.generator import TestGenerator
from app.models.enums import NodeKind
from app.models.model_node import ModelNode


def _orchestrator_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+psycopg://u:p@localhost/none",
        "executor_mode": "orchestrator",
        "ingestor_mode": "laravel",
        "ai_provider_mode": "stub",  # hermetic — no live model
        "embedding_provider": "stub",  # hermetic — no model download
        "runner_framework": "pest",
        "target_app_path": "/work/tests/fixtures/laravel-app",
        "target_repo_path": "/work/tests/fixtures/laravel-app",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_orchestrator_executor_is_fully_wired(db_session: AsyncSession) -> None:
    executor = build_run_executor(_orchestrator_settings())
    assert isinstance(executor, OrchestratorRunExecutor)

    # Target config is resolved PER-PROJECT at run time (ADR-0054): the provider is
    # wired (the runner + TargetEnv come from the Project, not composition env).
    assert isinstance(executor._target_provider, ProjectTargetProvider)

    # Real AI/embedding providers composed (stub here; claude_cli in the smoke).
    assert isinstance(executor._ai, StubAIProvider)
    assert isinstance(executor._embed, StubEmbeddingProvider)

    # The two B5 gaps, now closed: both are SESSION-SCOPED factories that build the
    # real production collaborators per run.
    resolver = executor._resolver_factory(db_session)
    assert isinstance(resolver, CrossLayerResolver)

    generator = executor._generator_factory(db_session)
    assert isinstance(generator, OrchestratorTargetGenerator)
    # The generator is AI-backed: it wraps the real endpoint + page generators
    # holding the composed provider.
    assert isinstance(generator._endpoint_gen, TestGenerator)
    assert isinstance(generator._page_gen, E2EGenerator)


def test_laravel_ingestor_is_wired() -> None:
    ingestor = build_ingestor(_orchestrator_settings())
    assert isinstance(ingestor, LaravelIngestorAdapter)
    # The repo is resolved from the Project at ingest time (ADR-0054); the adapter
    # just holds settings (for the deprecated env fallback), not a fixed repo path.
    assert isinstance(ingestor._settings, Settings)


def test_endpoint_spec_is_rebuilt_from_a_brain_node() -> None:
    node = ModelNode(
        project_id=uuid.uuid4(),
        kind=NodeKind.ENDPOINT,
        name="POST api/users/{id}",
        attributes={
            "method": "POST",
            "uri": "api/users/{id}",
            "name": "users.update",
            "auth_required": True,
            "validation": {
                "source": "form_request",
                "fields": [
                    {
                        "name": "email",
                        "raw_rules": ["required", "email", "unique:users,email"],
                        "required": True,
                        "type": "email",
                        "constraints": {"min": None, "max": None, "size": None},
                        "relational": {
                            "kind": "unique",
                            "table": "users",
                            "column": "email",
                        },
                    },
                    {
                        "name": "age",
                        "raw_rules": ["integer", "min:18"],
                        "required": False,
                        "type": "integer",
                        "constraints": {"min": 18.0, "max": None, "size": None},
                        "relational": None,
                    },
                ],
            },
        },
    )

    spec = endpoint_spec_from_node(node)
    assert spec.method == "POST" and spec.uri == "api/users/{id}"
    assert spec.route_name == "users.update" and spec.auth_required is True
    assert spec.path_params == ["id"]  # reconstructed from the uri
    assert [f.name for f in spec.validation_fields] == ["email", "age"]
    email = spec.validation_fields[0]
    assert email.required is True and email.type == "email"
    assert email.relational is not None and email.relational.table == "users"
    assert spec.validation_fields[1].constraints.min == 18.0
