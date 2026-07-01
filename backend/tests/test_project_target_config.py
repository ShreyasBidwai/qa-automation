"""Per-project target configuration — runs read it from the Project, not env (ADR-0054).

The resolver (project wins; env is a deprecated, logged fallback; honest error when a
required value is missing; stack → framework); the per-project provider + the executor
using the project's TargetEnv over env; the ingestor reading the project's repo; and
the create/update/response + RBAC for the target fields. Hermetic — stub runner, no
real exec.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.stub import StubAIProvider
from app.api.errors import ApiConfigError
from app.api.execution import OrchestratorRunExecutor
from app.api.ports import RunRequest
from app.api.project_target import (
    ResolvedTargetConfig,
    resolve_ai_provider_mode,
    resolve_target_config,
)
from app.api.real_execution import (
    LaravelIngestorAdapter,
    ProjectTargetProvider,
    build_runner_for,
    build_target_env_for,
)
from app.core.config import Settings
from app.embeddings.stub import StubEmbeddingProvider
from app.execution.php_test_runner import PhpTestRunner
from app.execution.types import ExecutionResult, PestScript, TargetEnv
from app.models.enums import NodeKind, Outcome, RunMode
from app.modes.selection import SelectionStrategyKind
from app.repositories.node_repository import NodeRepository
from app.repositories.project_repository import ProjectRepository
from tests.factories import make_node, make_project
from tests.test_api import _FakeResolver, _StubGenerator


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+psycopg://u:p@localhost:5432/db",
        "target_repo_path": "",
        "target_app_path": "",
        "target_base_url": None,
        "runner_framework": "pest",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


# --- AI provider: the project's choice, allow-listed, else instance default ---


def test_resolve_ai_provider_prefers_the_project_choice() -> None:
    project = make_project(settings={"ai_provider": "gemini"})
    settings = _settings(ai_provider_mode="claude_cli")
    assert resolve_ai_provider_mode(project, settings) == "gemini"


def test_every_selectable_provider_is_honoured_per_project() -> None:
    # Provider-agnostic: each selectable backend a project picks resolves to itself,
    # overriding the instance default — so anthropic/gemini/claude "just work".
    settings = _settings(ai_provider_mode="stub")
    for chosen in ("anthropic_api", "gemini", "claude_cli"):
        project = make_project(settings={"ai_provider": chosen})
        assert resolve_ai_provider_mode(project, settings) == chosen


def test_resolve_ai_provider_falls_back_for_absent_or_untrusted_values() -> None:
    settings = _settings(ai_provider_mode="claude_cli")
    # Absent, an unknown/garbage mode, a non-string, and the non-selectable 'stub'
    # all fall back to the instance default — a stored value is never trusted blindly.
    for stored in (
        {},
        {"ai_provider": "evil"},
        {"ai_provider": 123},
        {"ai_provider": "stub"},
    ):
        assert (
            resolve_ai_provider_mode(make_project(settings=stored), settings)
            == "claude_cli"
        )


# --- resolver: project wins, env is a deprecated fallback --------------------


def test_resolve_prefers_project_over_env() -> None:
    project = make_project(
        app_url="https://proj.example",
        settings={"repo_url": "/proj/repo", "stack": "laravel"},
    )
    settings = _settings(
        target_repo_path="/env/repo",
        target_base_url="https://env.example",
        runner_framework="playwright",
    )
    cfg = resolve_target_config(project, settings)
    assert cfg.repo_path == "/proj/repo"  # project wins over TARGET_REPO_PATH
    assert cfg.base_url == "https://proj.example"  # project wins over TARGET_BASE_URL
    assert cfg.app_path == "/proj/repo"
    assert cfg.framework == "pest"  # from stack=laravel, not env runner_framework


def test_resolve_falls_back_to_env_with_a_deprecation_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    project = make_project(app_url=None, settings={})  # nothing configured on it
    settings = _settings(
        target_repo_path="/env/repo",
        target_base_url="https://env.example",
        runner_framework="playwright",
    )
    caplog.set_level(logging.WARNING)
    cfg = resolve_target_config(project, settings)
    assert cfg.repo_path == "/env/repo"  # env fallback (deprecated)
    assert cfg.base_url == "https://env.example"
    assert cfg.framework == "playwright"  # no stack → env framework
    assert "env_fallback_deprecated" in caplog.text


# --- honest errors when a required value is missing -------------------------


def test_pest_runner_needs_no_base_url() -> None:
    cfg = ResolvedTargetConfig(
        repo_path="/r", app_path="/r", base_url=None, framework="pest"
    )
    assert isinstance(build_runner_for(cfg), PhpTestRunner)


def test_browser_run_without_base_url_fails_clearly() -> None:
    cfg = ResolvedTargetConfig(
        repo_path="/r", app_path="/r", base_url=None, framework="playwright"
    )
    with pytest.raises(ApiConfigError, match="target base URL"):
        build_runner_for(cfg)


def test_unknown_framework_fails_clearly() -> None:
    cfg = ResolvedTargetConfig(
        repo_path="/r", app_path="/r", base_url=None, framework="bogus"
    )
    with pytest.raises(ApiConfigError, match="unknown framework"):
        build_runner_for(cfg)


# --- the provider reads the project (real resolution, no run) ----------------


async def test_provider_resolves_runner_and_env_from_the_project(
    db_session: AsyncSession,
) -> None:
    project = await ProjectRepository(db_session).add(
        make_project(
            app_url="https://proj.example",
            settings={"repo_url": "/proj/repo", "stack": "laravel"},
        )
    )
    # Env carries DIFFERENT values — the project must win.
    settings = _settings(target_base_url="https://env.example")
    runner, target_env = await ProjectTargetProvider(settings).resolve(
        db_session, project.id
    )
    assert isinstance(runner, PhpTestRunner)  # stack=laravel → pest
    assert target_env.base_url == "https://proj.example"
    assert target_env.app_path == "/proj/repo"


async def test_provider_unknown_project_errors(db_session: AsyncSession) -> None:
    with pytest.raises(ApiConfigError, match="not found"):
        await ProjectTargetProvider(_settings()).resolve(db_session, uuid.uuid4())


# --- the executor uses the project's TargetEnv (not env) for the run ---------


class _CapturingRunner:
    """Records the TargetEnv it was handed (so a test can prove what the run used)."""

    framework = "capturing"

    def __init__(self) -> None:
        self.seen_env: TargetEnv | None = None

    def run(
        self, scripts: list[PestScript], target_env: TargetEnv
    ) -> list[ExecutionResult]:
        self.seen_env = target_env
        return [
            ExecutionResult(
                test_case_id=s.test_case_id,
                script_id=s.script_id,
                name=s.name,
                outcome=Outcome.FAIL,
                evidence_ref="ev",
            )
            for s in scripts
        ]

    def teardown(self, target_env: TargetEnv) -> None:
        return None


class _StubTargetProvider:
    """Real per-project resolution (project wins) but a stub runner (hermetic)."""

    def __init__(self, runner: _CapturingRunner, settings: Settings) -> None:
        self._runner = runner
        self._settings = settings

    async def resolve(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> tuple[_CapturingRunner, TargetEnv]:
        project = await ProjectRepository(session).get(project_id)
        assert project is not None
        cfg = resolve_target_config(project, self._settings)
        return self._runner, build_target_env_for(cfg, self._settings)


async def test_run_uses_project_target_config_over_env(
    db_session: AsyncSession,
) -> None:
    project = await ProjectRepository(db_session).add(
        make_project(
            app_url="https://proj.example",
            settings={"repo_url": "/proj/repo", "stack": "laravel"},
        )
    )
    await NodeRepository(db_session).add(
        make_node(project.id, kind=NodeKind.ENDPOINT, name="GET api/x")
    )
    settings = _settings(target_base_url="https://env.example")  # env differs
    capturing = _CapturingRunner()
    executor = OrchestratorRunExecutor(
        target_provider=_StubTargetProvider(capturing, settings),
        resolver_factory=lambda _s: _FakeResolver(),
        target_generator_factory=lambda s, _provider: _StubGenerator(s),
        ai_provider=StubAIProvider(),  # fixed provider (tests/stub path)
    )
    await executor.execute(
        session=db_session,
        project_id=project.id,
        request=RunRequest(
            mode=RunMode.B, strategy=SelectionStrategyKind.FULL_SWEEP, max_targets=50
        ),
    )
    assert capturing.seen_env is not None
    assert capturing.seen_env.base_url == "https://proj.example"  # project, not env
    assert capturing.seen_env.app_path == "/proj/repo"


async def test_executor_without_a_target_source_errors(
    db_session: AsyncSession,
) -> None:
    executor = OrchestratorRunExecutor(
        resolver_factory=lambda _s: _FakeResolver(),
        target_generator_factory=lambda s, _provider: _StubGenerator(s),
    )  # no target_provider, no runner+target_env
    with pytest.raises(ApiConfigError):
        await executor.execute(
            session=db_session,
            project_id=uuid.uuid4(),
            request=RunRequest(
                mode=RunMode.B, strategy=SelectionStrategyKind.FULL_SWEEP
            ),
        )


# --- the ingestor reads the project's repo, errors clearly when absent -------


async def test_ingestor_errors_when_project_has_no_repo(
    db_session: AsyncSession,
) -> None:
    project = await ProjectRepository(db_session).add(
        make_project(app_url=None, settings={})  # no repo_url
    )
    adapter = LaravelIngestorAdapter(
        settings=_settings(target_repo_path=""),  # no env fallback either
        embedding_provider=StubEmbeddingProvider(),
    )
    with pytest.raises(ApiConfigError, match="no repo configured"):
        await adapter.ingest(session=db_session, project_id=project.id)


async def test_ingestor_errors_when_project_is_unknown(
    db_session: AsyncSession,
) -> None:
    adapter = LaravelIngestorAdapter(
        settings=_settings(), embedding_provider=StubEmbeddingProvider()
    )
    with pytest.raises(ApiConfigError, match="not found"):
        await adapter.ingest(session=db_session, project_id=uuid.uuid4())


# --- API: create/update persists + returns the target fields; RBAC ----------


async def test_create_update_persists_and_returns_target_fields(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    created = (
        await client.post(
            "/api/v1/projects",
            json={
                "name": "T",
                "repo_url": "/repo/path",
                "app_url": "https://t.example",
                "stack": "laravel",
            },
        )
    ).json()
    assert created["repo_url"] == "/repo/path"
    assert created["app_url"] == "https://t.example"
    assert created["stack"] == "laravel"

    pid = created["id"]
    updated = (
        await client.patch(
            f"/api/v1/projects/{pid}",
            json={
                "repo_url": "/repo/new",
                "app_url": "https://new.example",
                "stack": "playwright",
            },
        )
    ).json()
    assert updated["repo_url"] == "/repo/new"
    assert updated["app_url"] == "https://new.example"
    assert updated["stack"] == "playwright"

    got = (await client.get(f"/api/v1/projects/{pid}")).json()
    assert got["app_url"] == "https://new.example" and got["stack"] == "playwright"


async def test_target_changes_require_manage_project(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    pid = (
        await client.post("/api/v1/projects", json={"name": "R", "repo_url": "/r"})
    ).json()["id"]
    outsider = (
        await client.post(
            "/api/v1/auth/signup",
            json={"email": f"o-{uuid.uuid4().hex[:8]}@e.test", "password": "passw0rd1"},
        )
    ).json()["access_token"]
    resp = await client.patch(
        f"/api/v1/projects/{pid}",
        json={"app_url": "https://x.example"},
        headers={"Authorization": f"Bearer {outsider}"},
    )
    assert resp.status_code == 404  # not a member → existence not leaked
