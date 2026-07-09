# ADR-0074 — Auto-provision the PHP target checkout for execution

**Status:** Accepted
**Date:** 2026-07-09

## Context

A run reads its target from the Project (ADR-0054). When `repo_url` is a git remote,
**ingestion** clones it read-only into a throwaway temp dir (`GitCliProvider.checkout`)
and builds the Brain statically (ADR-0055: no `vendor/`, no boot). **Execution** of the
API/backend layer is different: `PhpTestRunner` writes generated tests into the app's
`tests/Feature/_generated/` and runs `vendor/bin/pest|phpunit`, which needs a *real,
persistent checkout with `composer install` run* — the ingest temp clone is gone by then.

So `resolve_target_config` deliberately points execution at a local checkout
(`target_app_path` / the mounted `/targets/app`), and `lifecycle.py` already degrades
gracefully when that checkout is absent: it **skips the API layer** with an honest signal
(`"run composer install in the target"`). The gap: someone had to place + `composer
install` that checkout by hand, so backend testing was not fully frontend-driven.

## Decision

Add a **best-effort `TargetAppProvisioner`** (`app/execution/provision.py`) that, at run
time, keeps the execution checkout in sync with the project's `repo_url` and installs its
dependencies — so creating a project in the UI is enough to get backend testing:

- `GitCliProvider.sync_into(repo_url, ref, dest)` — a **persistent** read-only checkout
  (init → point `origin` → shallow-fetch the ref → force-detach), updating tracked files
  in place while **leaving untracked files (`vendor/`) intact** so deps aren't reinstalled
  every run. Still read-only (no push); token redacted from logs.
- `composer install` runs only when `vendor/autoload.php` is missing OR `composer.lock`
  changed since the last install (tracked by a small `.polaris-composer.sha` marker).
- Wired into `ProjectTargetProvider.resolve` (the per-run choke point), guarded by
  `target_provision_enabled` (default on). Runs only for a PHP (`pest`) run whose repo is
  a remote — a local-path repo (`app_path == repo`) and browser runs are no-ops.

**Best-effort is the load-bearing property:** any failure (clone error, composer failure)
is caught, logged, and returns `False`. The run then falls back to the existing graceful
"skip API layer" path — provisioning can only *enable* the backend layer, never *break* a
run.

**Single-target for now.** One `app_path` (the mounted `/targets/app`); a per-project
checkout dir for concurrent targets is deferred until multi-target is needed.

## Consequences

- Backend/API testing is fully frontend-driven: project `repo_url` → ingest → generate →
  run, with the checkout provisioned automatically. No manual terminal step.
- `composer install` runs the target's composer scripts (Laravel package discovery), i.e.
  it executes code from the target repo. This is acceptable because the target is trusted
  (we were engaged to test it) and runs inside the isolated, dual-DB-guarded runner with a
  secret-scrubbed environment (`process.scrubbed_environ`). Private *composer* package
  auth is a known follow-up (not yet wired).
- Idempotent + cheap on the steady state: an unchanged repo re-syncs tracked files and
  skips composer via the marker.
