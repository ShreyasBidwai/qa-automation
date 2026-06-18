"""GitCliProvider — read-only shallow checkout via the git CLI.

Builds an authenticated clone URL from a read-only token, shallow-fetches the
requested ref into a temp dir, checks it out detached, and resolves the real
HEAD SHA. All git calls go through an injectable CommandRunner (same pattern as
the artisan/php runners), so fast tests use a local fixture and no network.

READ-ONLY: only init/remote-add/fetch/checkout/rev-parse are ever run — there is
no push path. The token and the credentialed URL are NEVER logged (only the
redacted repo URL, ref, and resolved SHA).
"""

from __future__ import annotations

import logging
import shutil
import tempfile

from app.ingestion.commands import CommandRunner, check_output, run_subprocess
from app.ingestion.errors import IngestionCommandError

from .errors import GitCheckoutError
from .types import CheckoutHandle
from .url import authenticated_url, redact_url

logger = logging.getLogger("app.git")

_TMP_PREFIX = "qa-git-checkout-"


class GitCliProvider:
    def __init__(
        self,
        *,
        runner: CommandRunner = run_subprocess,
        git_path: str = "git",
        token: str | None = None,
        token_username: str = "oauth2",
        timeout: float = 120.0,
    ) -> None:
        self._runner = runner
        self._git = git_path
        self._token = token
        self._token_username = token_username
        self._timeout = timeout

    def _run(self, args: list[str], *, what: str) -> str:
        result = self._runner([self._git, *args], None, self._timeout)
        return check_output(result, what=what)

    def checkout(self, repo_url: str, ref: str) -> CheckoutHandle:
        tmp = tempfile.mkdtemp(prefix=_TMP_PREFIX)
        # The credentialed URL is used only in the fetch command, never logged.
        clone_url = authenticated_url(repo_url, self._token, self._token_username)
        try:
            self._run(["init", "-q", tmp], what="git init")
            self._run(
                ["-C", tmp, "remote", "add", "origin", clone_url],
                what="git remote add",
            )
            # Shallow-fetch the ref (branch, tag, or SHA) then detach onto it.
            self._run(
                ["-C", tmp, "fetch", "--no-tags", "--depth", "1", "origin", ref],
                what="git fetch",
            )
            self._run(
                ["-C", tmp, "checkout", "--detach", "-q", "FETCH_HEAD"],
                what="git checkout",
            )
            sha = self._run(["-C", tmp, "rev-parse", "HEAD"], what="git rev-parse")
        except IngestionCommandError as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            # Redact: never let the token or credentialed URL into the error.
            raise GitCheckoutError(
                f"checkout of {redact_url(repo_url)}@{ref} failed"
            ) from exc

        resolved = sha.strip()
        logger.info(
            "git.checkout",
            extra={"repo": redact_url(repo_url), "ref": ref, "sha": resolved},
        )
        return CheckoutHandle(path=tmp, sha=resolved, ref=ref)

    def cleanup(self, handle: CheckoutHandle) -> None:
        """Remove the temp working tree. Idempotent — safe on success and failure."""
        shutil.rmtree(handle.path, ignore_errors=True)
