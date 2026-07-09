"""Auto-provision a PHP target's local checkout so the API/Pest layer can execute
(ADR-0074).

Clone-at-ingest reads the repo into a throwaway temp clone (no ``vendor/``); test
EXECUTION needs a persistent, ``composer install``-ed checkout at ``app_path`` for
Pest/PHPUnit to run. This provisioner keeps that checkout in sync from the project's
``repo_url`` and installs deps — so a run is fully frontend-driven, with no manual
terminal step. Single-target for now: one ``app_path`` (the mounted ``/targets/app``).

BEST-EFFORT by design: any failure returns ``False`` and the run falls back to the
graceful "skip API layer" path (``lifecycle.py``) — provisioning can only ENABLE the
backend layer, never break a run. The clone is READ-ONLY (no push); the token is
redacted from every log by the underlying git provider.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Protocol

from app.execution.process import Process, run_process

logger = logging.getLogger("app.execution")

_COMPOSER_MARKER = ".polaris-composer.sha"


class ProvisionError(RuntimeError):
    """A target-app provisioning step failed (caught + downgraded to best-effort)."""


class GitSync(Protocol):
    """The read-only persistent-checkout capability (``GitCliProvider.sync_into``)."""

    def sync_into(self, repo_url: str, ref: str, dest: str) -> str: ...


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TargetAppProvisioner:
    """Keeps ``app_path`` a current, dependency-installed checkout of the target."""

    def __init__(
        self,
        *,
        git_sync: GitSync,
        process: Process = run_process,
        composer_path: str = "composer",
        composer_timeout: float = 600.0,
    ) -> None:
        self._git = git_sync
        self._process = process
        self._composer = composer_path
        self._composer_timeout = composer_timeout

    def ensure_php_checkout(
        self, *, repo_path: str, app_path: str, framework: str, ref: str = "HEAD"
    ) -> bool:
        """Ensure ``app_path`` is a current checkout of ``repo_path`` with ``vendor/``.

        A no-op (returns ``True``) unless this is a PHP run whose repo is a remote to
        clone:
          - a non-``pest`` framework → the browser layer needs no local PHP checkout;
          - ``repo_path == app_path`` (or either empty) → the repo IS already a local
            checkout (``resolve_target_config`` sets ``app_path = repo`` for a local
            path), so there is nothing to sync.
        Returns ``False`` on any failure (best-effort; the run then skips the API).
        """
        if framework != "pest":
            return True
        if not repo_path or not app_path or repo_path == app_path:
            return True
        try:
            self._git.sync_into(repo_path, ref, app_path)
            self._composer_install_if_needed(app_path)
            return True
        except Exception as exc:  # noqa: BLE001 — best-effort: must never break a run
            logger.warning(
                "target_provision.failed",
                extra={"app_path": app_path, "error": str(exc)},
            )
            return False

    def _composer_install_if_needed(self, app_path: str) -> None:
        """Run ``composer install`` unless ``vendor/`` is already present AND installed
        for the current ``composer.lock`` (tracked via a small marker file)."""
        root = Path(app_path)
        autoload = root / "vendor" / "autoload.php"
        lock = root / "composer.lock"
        marker = root / _COMPOSER_MARKER
        want = _hash_file(lock) if lock.exists() else "no-lock"
        if (
            autoload.exists()
            and marker.exists()
            and marker.read_text(encoding="utf-8").strip() == want
        ):
            logger.info(
                "target_provision.composer_cached", extra={"app_path": app_path}
            )
            return
        # ``run_process`` scrubs Polaris' secrets from the child env; the target reads
        # its own ``.env`` for app config. ``--no-scripts`` is NOT passed: Laravel's
        # package discovery runs in composer scripts, and the target repo is trusted (we
        # were engaged to test it) inside an isolated, dual-DB-guarded runner.
        result = self._process(
            [
                self._composer,
                "install",
                "--no-interaction",
                "--prefer-dist",
                "--no-progress",
            ],
            app_path,
            {"COMPOSER_ALLOW_SUPERUSER": "1"},
            self._composer_timeout,
        )
        if result.returncode != 0:
            raise ProvisionError(
                f"composer install failed (exit {result.returncode}): "
                f"{result.stderr[-400:].strip()}"
            )
        try:
            marker.write_text(want, encoding="utf-8")
        except OSError:
            pass  # the marker is only an optimization; a miss just re-installs next run
        logger.info("target_provision.composer_installed", extra={"app_path": app_path})
