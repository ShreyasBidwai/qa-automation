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

    # --- Authentication (B2; ADR-0030) ----------------------------------------
    # Server-side opaque sessions: a bearer token (hashed at rest) valid for this
    # long; password-reset tokens are single-use and short-lived.
    session_ttl_seconds: int = 1_209_600  # 14 days
    password_reset_ttl_seconds: int = 3_600  # 1 hour
    org_invite_ttl_seconds: int = 604_800  # 7 days (B3; ADR-0033)

    # --- Rate limiting (B11; ADR-0046) ----------------------------------------
    # Per-IP fixed-window caps on the sensitive auth endpoints (in-memory, single
    # instance — see app.core.rate_limit). Sensible defaults; tune via env.
    auth_rate_limit_window_seconds: int = 60
    auth_signin_rate_limit: int = 10  # sign-in attempts per IP per window
    auth_signup_rate_limit: int = 10  # sign-ups per IP per window
    auth_password_reset_rate_limit: int = 5  # reset requests per IP per window

    # --- Durable job queue (B4; ADR-0034) -------------------------------------
    # The in-process worker poller drains the `jobs` table; enabled in the
    # packaged app, off by default (the fast lane drives jobs via the dispatch
    # hint and tests the worker directly).
    job_worker_enabled: bool = False
    job_poll_interval_seconds: float = 1.0
    job_backoff_base_seconds: float = 2.0
    job_stuck_after_seconds: int = 300  # a running job older than this is "stuck"
    # Identifies the claiming worker in the job lease (B5, ADR-0036).
    worker_id: str = "runner"

    # --- Run / ingest composition (packaging; docs/running.md) ----------------
    # What the API's run-executor and ingestor ports resolve to at server start
    # (composed in app.__main__, NOT create_app — tests stub the ports per-test).
    # DEFAULT to safe stubs so a clone boots and a stub run completes end-to-end
    # with zero external credentials or toolchains. The real orchestrator/ingestor
    # need the runner toolchains (Pest/Playwright) + git and are an opt-in.
    #   executor_mode: stub | orchestrator     ingestor_mode: stub | laravel
    executor_mode: str = "stub"
    ingestor_mode: str = "stub"

    # --- Real execution wiring (orchestrator mode; runner worker) -------------
    # The orchestrator executor drives a real per-stack runner against a target.
    # These configure WHERE/AGAINST WHAT it runs; only consulted in orchestrator
    # mode (the slim backend never executes — B5/ADR-0036).
    runner_framework: str = "pest"  # pest | playwright
    # The target app the runner executes in (Pest: the Laravel app dir; Playwright:
    # the node project dir) and the repo the Laravel ingestor reads.
    target_app_path: str = ""
    target_repo_path: str = ""
    # The writable, EPHEMERAL test DB the runner uses (dual-DB rule, Arch §9) — must
    # be a throwaway test target, never a real database.
    execution_db_url: str = "sqlite::memory:"
    # Where the runner writes evidence (JUnit, logs, traces).
    evidence_dir: str = "/tmp/polaris-evidence"
    # Where failure screenshots are stored on local disk (gitignored; ADR-0051). The
    # single indirection (app.screenshots) owns this path — swap to object storage at
    # deploy. Relative to the backend working dir; gitignored via backend/.gitignore.
    screenshot_dir: str = "var/screenshots"
    # The running target frontend a browser runner drives (Playwright only).
    target_base_url: str | None = None

    # --- AI layer (pluggable; dev shells to `claude -p`) (TRD §6, Arch §8) ---
    # Provider selection: claude_cli (dev) | stub (tests). api/self-host land later.
    # NOTE: the packaged backend image ships no `claude` CLI; switching to
    # claude_cli requires providing it (docs/running.md).
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

    # --- Embeddings (pluggable; local fastembed dev/prod, stub for tests) ---
    # Provider selection: local (fastembed ONNX) | stub (tests, no download).
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    # MUST match the model_nodes.embedding column dimension (migration 0005).
    embedding_dim: int = 384

    # --- Git ingestion source (READ-ONLY; there is no push path, ever) ---
    # A read-only access token, injected into the clone URL at runtime and NEVER
    # logged (a secret; comes from the environment / secret store, not code).
    git_token: str | None = None
    git_token_username: str = "oauth2"
    git_clone_timeout_seconds: float = 120.0

    # --- Target-account credentials encryption (ADR-0053) ---
    # A urlsafe-base64 32-byte Fernet key used to encrypt target-app account secrets
    # at rest. Comes from the environment / secret store — NEVER hardcoded or in the
    # repo. Absent ⇒ the credentials write path refuses (no plaintext is ever stored)
    # and is itself a secret (never logged). Generate: Fernet.generate_key().
    target_credentials_key: str | None = None

    # --- Brain resolver (T2.4) — hybrid vector + lexical NL→node resolution ---
    # Blended score = vector_weight * cosine_sim + lexical_weight * lexical.
    resolver_vector_weight: float = 0.6
    resolver_lexical_weight: float = 0.4
    # Below this best cosine similarity, vectors are treated as uninformative and
    # resolution falls back to pure lexical (codebase facts are ground truth).
    resolver_vector_min_similarity: float = 0.15
    # Top blended score below this flags the resolution low-confidence.
    resolver_confidence_threshold: float = 0.35
    # Vector ANN candidates to blend, and the 1-hop subgraph neighbour cap.
    resolver_vector_candidates: int = 20
    resolver_subgraph_max_neighbors: int = 10


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton (validated on first access).

    Required fields (e.g. ``database_url``) are populated from the environment;
    a missing one raises ``ValidationError`` here (fail fast, Standards §6).
    """
    # Values are loaded from the environment by pydantic-settings, not passed in.
    return Settings()  # type: ignore[call-arg]
