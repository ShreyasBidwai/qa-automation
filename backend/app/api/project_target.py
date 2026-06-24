"""Per-project target configuration resolution (ADR-0054).

Target config — where the app's source lives (repo path/URL), the running app's base
URL, and the stack → execution framework — is PER-PROJECT data on the ``Project``, not
instance config. This resolves the effective config for a run:

- the **PROJECT value wins**;
- an instance env var is a **deprecated fallback**, used only when the project has no
  value (and logged, so a deployment can migrate off it) — so nothing breaks mid
  transition;
- a missing *required* value raises a clear, honest error at run start, not a crash.

Infra-level switches (executor/ingestor mode, AI/embedding providers, the credentials
encryption key) stay in env and are NOT resolved here. None of these values are secret
(a private-repo token is handled separately — see ADR-0054 / ADR-0053).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config import Settings
from app.models.project import Project

logger = logging.getLogger("app.api.project_target")

# A project's stack selects the execution framework (the runner). An unknown/absent
# stack falls back to the configured ``runner_framework`` (the env default).
_FRAMEWORK_BY_STACK: dict[str, str] = {"laravel": "pest"}


@dataclass(frozen=True)
class ResolvedTargetConfig:
    """The effective per-project target config for one run (project-first)."""

    repo_path: str  # where the app source lives (a local path or, later, a git URL)
    app_path: str  # the app working dir for the runner (defaults to the repo)
    base_url: str | None  # the running app a browser runner drives
    framework: str  # pest | playwright — derived from the project stack


def _coalesce(
    project_value: str | None, env_value: str | None, *, field: str, env_name: str
) -> str | None:
    """Project value wins; else the env var as a DEPRECATED fallback (logged)."""
    if project_value:
        return project_value
    if env_value:
        logger.warning(
            "project_target.env_fallback_deprecated",
            extra={"field": field, "env": env_name},
        )
        return env_value
    return None


def resolve_target_config(project: Project, settings: Settings) -> ResolvedTargetConfig:
    """Resolve a project's target config, preferring the project over env (ADR-0054)."""
    project_settings = project.settings or {}
    repo = (
        _coalesce(
            str(project_settings.get("repo_url") or "") or None,
            settings.target_repo_path or None,
            field="repo",
            env_name="TARGET_REPO_PATH",
        )
        or ""
    )
    # The app working dir is the repo checkout; keep the env app-path as a last resort.
    app_path = repo or settings.target_app_path or ""
    base_url = _coalesce(
        project.app_url,
        settings.target_base_url,
        field="base_url",
        env_name="TARGET_BASE_URL",
    )
    stack = str(project_settings.get("stack") or "")
    framework = _FRAMEWORK_BY_STACK.get(stack) or settings.runner_framework
    return ResolvedTargetConfig(
        repo_path=repo, app_path=app_path, base_url=base_url, framework=framework
    )
