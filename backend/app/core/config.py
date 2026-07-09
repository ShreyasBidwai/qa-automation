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
    # Staff impersonation sessions are deliberately short — a support action, not a
    # login (ADR-0071). 30 minutes; a forgotten impersonation self-expires.
    impersonation_ttl_seconds: int = 1_800
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
    # Watchdog: a run exceeding this wall-clock budget is force-failed (terminally,
    # no retry) with an incident, so a hung run can never hold the queue forever
    # (architecture-review DO-FIRST #2). Generous — a large full-sweep generation is
    # legitimately long; this only catches a genuinely wedged run.
    job_max_duration_seconds: float = 1800.0
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
    # Optional route enrichment (ADR-0055): when ON *and* the target app happens to
    # boot, merge ``php artisan route:list`` (dynamic / package-registered routes the
    # static parser can't see) into the statically-parsed routes. OFF by default and
    # fully FAIL-SAFE — ingestion never depends on it and falls back to the static set
    # on any error. Opt in to widen module/endpoint coverage for apps that register
    # routes outside ``routes/*.php`` (needs a composer-installed, bootable checkout).
    ingest_artisan_enrichment: bool = False

    # --- Real execution wiring (orchestrator mode; runner worker) -------------
    # The orchestrator executor drives a real per-stack runner against a target.
    # These configure WHERE/AGAINST WHAT it runs; only consulted in orchestrator
    # mode (the slim backend never executes — B5/ADR-0036).
    runner_framework: str = "pest"  # pest | playwright
    # Frontend crawl phase (T4.2): the node project dir holding the Playwright
    # ``crawl_page.mjs`` driver (+ a resolvable node_modules). Empty ⇒ a mode_b run
    # skips the crawl phase. Set it to make one run cover backend + DB + frontend.
    crawl_driver_dir: str = ""
    # Interaction crawling (T4.2 "crawler depth"): the driver clicks a few SAFE in-page
    # controls (tabs/filters/"load more") to surface endpoints that only fire on
    # interaction. Bounded + denylisted in the driver — it NEVER submits a form or
    # clicks a destructive control. Disable, or cap per page, here.
    crawl_interactions_enabled: bool = True
    crawl_max_interactions: int = 5
    # The target app the runner executes in (Pest: the Laravel app dir; Playwright:
    # the node project dir) and the repo the Laravel ingestor reads.
    target_app_path: str = ""
    target_repo_path: str = ""
    # The writable, EPHEMERAL test DB the runner uses (dual-DB rule, Arch §9) — must
    # be a throwaway test target, never a real database.
    execution_db_url: str = "sqlite::memory:"
    # Where the runner writes evidence (JUnit, logs, traces).
    evidence_dir: str = "/tmp/polaris-evidence"
    # Where failure screenshots live behind the single indirection (app.screenshots,
    # ADR-0051). ``screenshot_storage`` selects the backend:
    #   local — a gitignored on-disk dir (``screenshot_dir``); single-box/dev only,
    #           since capture (runner) and serve (control plane) must share a disk.
    #   s3    — an S3-compatible bucket (AWS S3 / MinIO / any S3 API); the decoupled
    #           topology (ADR-0036) needs this so the runner and control plane share
    #           storage. Credentials come from boto3's env/IAM chain, never here.
    screenshot_storage: str = "local"  # local | s3
    screenshot_dir: str = "var/screenshots"
    # S3 backend (screenshot_storage=s3). The bucket is required; the endpoint is set
    # for S3-compatible stores like MinIO (empty ⇒ real AWS). A key prefix namespaces
    # the objects within a shared bucket. AWS credentials are NEVER read from here —
    # boto3 resolves them from the standard chain (env vars / instance role).
    screenshot_s3_bucket: str = ""
    screenshot_s3_endpoint_url: str | None = None
    screenshot_s3_region: str = "us-east-1"
    screenshot_s3_prefix: str = "screenshots"
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
    # Optional: route `claude -p` through a host-side bridge (app/bridge/server.py,
    # run via `make bridge`) instead of running the CLI in-process. The runner
    # container can't safely use the host's interactive Claude login — a cross-uid,
    # read-write ~/.claude bind mount corrupts/rotates the shared OAuth token, logging
    # the host out on every up/down. With a bridge the credentials stay on the HOST;
    # the container POSTs to this URL with the shared token. Empty = run `claude`
    # directly in-process (single-box dev). docs/running-real.md.
    claude_bridge_url: str | None = None
    claude_bridge_token: str | None = None
    # Recommended per-call context budget callers pass to generate(); the
    # provider enforces whatever budget_tokens it is given.
    ai_max_budget_tokens: int = 120000
    ai_budget_strategy: str = "truncate"  # truncate | raise
    # External-call timeout + bounded retry/backoff (Standards §12).
    ai_timeout_seconds: float = 120.0
    ai_max_attempts: int = 3
    ai_retry_base_delay_seconds: float = 0.5
    ai_retry_max_delay_seconds: float = 8.0

    # --- Gemini provider (AI_PROVIDER_MODE=gemini, or chosen per project) ------
    # The API key is a SECRET, env-only: never hardcoded, logged, stored in the DB,
    # or returned in a payload. It is sent to Google via the ``x-goog-api-key``
    # HEADER (never the URL — a key in a URL leaks into logs/history). Absent ⇒ the
    # gemini provider refuses with a clear error rather than calling unauthenticated.
    gemini_api_key: str | None = None
    gemini_generate_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    # Rate-limit-aware model fallback (generation path). Gemini returns 429
    # RESOURCE_EXHAUSTED for BOTH per-minute and per-day exhaustion, distinguished
    # only by the response body (parsed, never hardcoded). A per-day-exhausted model
    # is skipped and the NEXT model in the chain is tried; a per-minute 429 waits
    # (honoring the API's RetryInfo) and retries the SAME model, bounded.
    #   GEMINI_MODEL_CHAIN: comma-separated, tried in order. Empty ⇒ a one-element
    #   chain of ``gemini_generate_model`` (the single-model path is unchanged).
    gemini_model_chain: str = ""
    # Max per-minute waits on ONE model before giving up on it (never unbounded).
    gemini_max_minute_retries: int = 3
    # Cap for a single per-minute wait (also the default when the 429 omits a
    # RetryInfo). Keeps a hostile/garbled retryDelay from stalling the run.
    gemini_minute_retry_cap_seconds: float = 60.0

    # --- Billing / Stripe (B6, ADR-0069) ---------------------------------------
    # SECRETS, env-ONLY (never in the DB, a payload, a URL, or logs; sent to Stripe via
    # the Authorization header). Unset ⇒ billing stays in stub mode: plans are still
    # seeded and staff-assignable (ADR-0069), only LIVE payment collection is inert. Set
    # these + BILLING_MODE=stripe to activate the Stripe integration.
    billing_mode: str = "stub"  # stub | stripe
    stripe_api_key: str | None = None
    stripe_webhook_secret: str | None = None

    # --- Anthropic API provider (AI_PROVIDER_MODE=anthropic_api) ---------------
    # The PRODUCTION Claude backend — the Messages API directly (no `claude` CLI).
    # The API key is a SECRET, env-ONLY: never hardcoded, logged, stored in the DB,
    # or returned in a payload. It is sent via the ``x-api-key`` HEADER (never the
    # URL). Absent ⇒ the provider refuses with a clear error rather than calling
    # unauthenticated. Uses ai_generate_model (frontier) + ai_triage_model (cheap).
    anthropic_api_key: str | None = None
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_version: str = "2023-06-01"
    # Output cap for a generate call (the Messages API requires max_tokens); triage
    # uses a small internal cap since its reply is a single label.
    anthropic_max_output_tokens: int = 8192

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

    # --- Auto-provision the PHP target checkout for execution (ADR-0074) ---
    # When on, a run whose repo is a git URL auto-syncs it into ``target_app_path`` and
    # runs ``composer install`` before the Pest/PHPUnit layer, so backend testing is
    # fully frontend-driven (no manual checkout). Best-effort: on failure the run falls
    # back to the graceful "skip API layer" path. Set false to require a pre-placed
    # checkout (the old manual model).
    target_provision_enabled: bool = True
    composer_install_timeout_seconds: float = 600.0

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
