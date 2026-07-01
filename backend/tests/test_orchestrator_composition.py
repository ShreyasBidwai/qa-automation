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
from pathlib import Path

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
from app.git.types import CheckoutHandle
from app.models.enums import NodeKind
from app.models.model_node import ModelNode
from tests.factories import make_project

_LARAVEL_FIXTURE = str(Path(__file__).parent / "fixtures" / "laravel-app")


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

    generator = executor._generator_factory(db_session, executor._ai)
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


def test_build_auth_strategy_selects_totp_when_a_secret_is_present() -> None:
    # The crawl uses automated TOTP (unattended 2FA) when the resolved AuthConfig
    # carries a totp_secret, and manual-OTP semantics otherwise.
    from app.api.execution import _build_auth_strategy
    from app.auth.strategy import ManualOtpStrategy, TotpStrategy

    assert isinstance(_build_auth_strategy("/tmp/crawl", use_totp=True), TotpStrategy)
    manual = _build_auth_strategy("/tmp/crawl", use_totp=False)
    assert isinstance(manual, ManualOtpStrategy) and not isinstance(manual, TotpStrategy)


class _FakeGitProvider:
    """Records checkout/cleanup and hands back a fixed local tree — so the git
    ingest path is exercised without a real remote (READ-ONLY: no push method)."""

    def __init__(self, path: str) -> None:
        self._path = path
        self.checked_out: list[tuple[str, str]] = []
        self.cleaned = 0

    def checkout(self, repo_url: str, ref: str) -> CheckoutHandle:
        self.checked_out.append((repo_url, ref))
        return CheckoutHandle(path=self._path, sha="a" * 40, ref=ref)

    def cleanup(self, handle: CheckoutHandle) -> None:
        self.cleaned += 1


async def _project_with_repo(session: AsyncSession, repo_url: str) -> uuid.UUID:
    project = make_project(settings={"repo_url": repo_url, "stack": "laravel"})
    session.add(project)
    await session.flush()
    return project.id


async def test_ingest_clones_a_git_url_read_only_then_ingests(
    db_session: AsyncSession,
) -> None:
    # A project whose repo_url is a git remote → the adapter CLONES it (read-only),
    # builds the Brain from the checkout, and cleans up the temp tree.
    provider = _FakeGitProvider(_LARAVEL_FIXTURE)
    adapter = LaravelIngestorAdapter(
        settings=_orchestrator_settings(),
        embedding_provider=StubEmbeddingProvider(),
        git_provider=provider,
    )
    pid = await _project_with_repo(db_session, "https://git.example/acme/app.git")

    result = await adapter.ingest(session=db_session, project_id=pid)

    assert provider.checked_out == [("https://git.example/acme/app.git", "HEAD")]
    assert provider.cleaned == 1  # the temp clone is always removed
    assert result["mode"] == "laravel"
    assert result["source_sha"] == "a" * 40  # the clone's resolved SHA flowed through
    assert result["nodes"]  # the Brain was built from the checkout


async def test_ingest_reads_a_local_checkout_without_cloning(
    db_session: AsyncSession,
) -> None:
    # A project whose repo_url is a local path → NO clone; the path is read directly.
    provider = _FakeGitProvider(_LARAVEL_FIXTURE)
    adapter = LaravelIngestorAdapter(
        settings=_orchestrator_settings(),
        embedding_provider=StubEmbeddingProvider(),
        git_provider=provider,
    )
    pid = await _project_with_repo(db_session, _LARAVEL_FIXTURE)

    result = await adapter.ingest(session=db_session, project_id=pid)

    assert provider.checked_out == []  # a local path is never cloned
    assert result["mode"] == "laravel" and result["nodes"]


def test_build_crawler_gates_on_driver_dir_and_base_url(monkeypatch) -> None:
    # The crawl phase engages ONLY when the runner has a crawl driver dir configured
    # (the real image sets CRAWL_DRIVER_DIR=/opt/crawl) AND the project has an app_url.
    from types import SimpleNamespace

    from app.api import execution as ex
    from app.execution.types import DbHandle, DbRole, TargetEnv

    def _env(base_url: str | None) -> TargetEnv:
        return TargetEnv(
            app_path="/x",
            execution_db=DbHandle("sqlite::memory:", DbRole.WRITABLE_TEST, True),
            evidence_dir="/e",
            base_url=base_url,
        )

    def _settings(driver_dir: str) -> object:
        return SimpleNamespace(
            crawl_driver_dir=driver_dir,
            crawl_interactions_enabled=True,
            crawl_max_interactions=5,
        )

    # Driver dir + app_url → a real crawler is built.
    monkeypatch.setattr(ex, "get_settings", lambda: _settings("/opt/crawl"))
    assert ex._build_crawler(_env("https://app.qa")) is not None
    # No app_url → skipped (nothing to crawl).
    assert ex._build_crawler(_env(None)) is None
    # No driver dir → skipped (the toolchain isn't wired).
    monkeypatch.setattr(ex, "get_settings", lambda: _settings(""))
    assert ex._build_crawler(_env("https://app.qa")) is None
