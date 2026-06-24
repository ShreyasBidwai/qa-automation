# ADR-0054: Per-project target configuration (runs read it from the Project, not env)

- Status: Accepted
- Date: 2026-06-24
- Deciders: Engineering

## Context

Target configuration — where the app's source lives (repo path/URL), the running
app's base URL, and the stack/framework — is **per-project** data. The first-real-run
setup put `TARGET_REPO_PATH` / `TARGET_BASE_URL` (and the runner framework) in
instance **env**, which would make Polaris a single-project tool and contradicts the
multi-project model (projects list, project settings, the per-project credentials
vault). This corrects that architecture smell.

## What already existed (verified, read-only)

The per-project **fields already exist** — nothing new was added to the model and
**no migration was needed**:

- `Project.app_url` — a first-class column (the target base URL).
- `Project.settings` JSONB — `repo_url`, `stack`, `auth_config_ref` (the established
  per-project pattern, same as the credentials reference).
- `ProjectCreate` / `ProjectUpdate` / `ProjectResponse` already accept + return
  `repo_url`, `app_url`, `stack` (and `auth_config_ref`). Project mutations are already
  gated on `MANAGE_PROJECT`.

The smell was purely in the **run wiring**: the executor + ingestor were built once at
startup from env (`build_target_env(settings)`, `build_runner(settings)`,
`LaravelIngestorAdapter(repo_path=settings.target_repo_path)`) — one target config for
every project.

## Decision

### Runs read target config from the Project

A new resolver, `app/api/project_target.resolve_target_config(project, settings)`,
produces the effective per-project config (`repo_path`, `app_path`, `base_url`,
`framework`). The run path now resolves it **per run, from the run's project**:

- `OrchestratorRunExecutor` takes a `ProjectTargetProvider` (reads the Project and
  builds the run's `(runner, TargetEnv)` from it). The DB-state phase still binds to
  the disposable execution DB by URL (infra). The executor keeps a fixed
  `runner + target_env` path for the stub/test wiring (backward-compatible).
- `LaravelIngestorAdapter.ingest` reads the project's repo via the resolver instead of
  a constructor env `repo_path`.

`base_url ← project.app_url`; `repo_path ← project.settings["repo_url"]`;
`framework ← project.stack` (laravel → pest; an unknown/absent stack falls back to the
env `runner_framework`). The app working dir defaults to the repo.

### Precedence — project wins, env is a deprecated fallback

For each value: the **project wins**; if the project has none, the matching env var is
used as a **deprecated fallback** and a warning is logged (`project_target
.env_fallback_deprecated`), so a deployment can migrate off env without breaking
mid-transition. When both are absent and the value is required, the run fails at start
with a **clear, honest error** — e.g. `"project has no target base URL configured —
set app_url on the project"` for a browser run, or `"project has no repo configured —
set repo_url on the project"` for laravel ingestion — not a crash.

### What stays in env

Infra-level switches stay in env and are NOT moved: `EXECUTOR_MODE`, `INGESTOR_MODE`,
`AI_PROVIDER_MODE`, `EMBEDDING_PROVIDER`, the disposable `EXECUTION_DB_URL`,
`EVIDENCE_DIR`, and `TARGET_CREDENTIALS_KEY` (the credentials encryption key, ADR-0053).

## Repo auth / private-repo token (honest)

`GIT_TOKEN` is **still env** and intentionally NOT moved here. It is a *secret*, so it
must never be a plain column and never returned in a payload. Per-project git checkout
(clone from `repo_url` using a per-project token) is **not yet wired** — the ingestor
reads an already-checked-out local path today — so there is nothing in the run path
that would consume a per-project repo token yet. When per-project checkout lands, the
repo token belongs in the **encrypted credentials-vault pattern** (ADR-0053), as a
write-only per-project secret — NOT a plain column, NOT env. Flagged so it isn't
forgotten. `auth_config_ref` is a non-secret per-project reference and already lives in
`settings`.

## Consequences

- Runs are per-project end-to-end: two projects with different repos / base URLs / 
  stacks run correctly from one instance.
- Backward-safe: existing env-configured deployments keep working (deprecated fallback
  + warning); existing projects without target fields don't break (optional, honest
  error only when a run actually needs a missing value).
- No model change, no migration (head stays `0031_target_credentials`).

### Known remaining env read

`target_has_factories(settings.target_repo_path)` (whether generated tests may use
model factories, ADR-0037) is a generation heuristic derived from the repo and still
reads the env repo path. It has a runtime fallback when factories are absent, so it
only affects generation setup quality, not correctness — moving it per-project waits on
per-project repo checkout. Documented, not fixed here.
