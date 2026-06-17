"""Application configuration via environment (12-factor, Standards §6).

Settings are loaded from the environment (and a local ``.env`` in dev). Required
values have no default, so a missing one raises ``ValidationError`` at load time
— the app fails fast at startup rather than running misconfigured.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    app_env: str = "development"
    app_port: int = 8000
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    request_id_header: str = "X-Request-ID"

    # --- Database (required: no default → fail fast if absent) ---
    database_url: str = Field(
        ...,
        description="SQLAlchemy URL, e.g. postgresql+psycopg://user:pass@host:5432/db",
    )
    db_pool_size: int = 10
    db_pool_max_overflow: int = 5

    # --- Startup DB connect retries (bounded, Standards §11–12) ---
    db_connect_max_retries: int = 10
    db_connect_base_delay_seconds: float = 0.5
    db_connect_max_delay_seconds: float = 8.0

    # --- Graceful shutdown ---
    shutdown_drain_timeout_seconds: float = 30.0

    # --- AI layer (pluggable; dev shells to `claude -p`) (TRD §6, Arch §8) ---
    # Provider selection: claude_cli (dev) | stub (tests). api/self-host land later.
    ai_provider_mode: str = "claude_cli"
    # Model tiering is config-driven so prod can swap to API/self-host with no
    # core change. Frontier for generate, cheap for triage (Sprint 7).
    ai_generate_model: str = "claude-opus-4-8"
    ai_triage_model: str = "claude-haiku-4-5"
    claude_cli_path: str = "claude"
    # Recommended per-call context budget callers pass to generate(); the
    # provider enforces whatever budget_tokens it is given.
    ai_max_budget_tokens: int = 120000
    ai_budget_strategy: str = "truncate"  # truncate | raise
    # External-call timeout + bounded retry/backoff (Standards §12).
    ai_timeout_seconds: float = 120.0
    ai_max_attempts: int = 3
    ai_retry_base_delay_seconds: float = 0.5
    ai_retry_max_delay_seconds: float = 8.0


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton (validated on first access).

    Required fields (e.g. ``database_url``) are populated from the environment;
    a missing one raises ``ValidationError`` here (fail fast, Standards §6).
    """
    # Values are loaded from the environment by pydantic-settings, not passed in.
    return Settings()  # type: ignore[call-arg]
