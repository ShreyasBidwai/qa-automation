"""Injectable subprocess runner for the runner toolchain (Standards §7, §12).

Same pattern as the ingestion CommandRunner (T1.3) but carries an environment
overlay so the runner can point the target app at the writable test DB. A plain
callable so tests inject a spy and never spawn a live ``pest``.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from .errors import RunnerProcessError, RunnerTimeout


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


# (argv, cwd, env_overlay, timeout_seconds) -> ProcessResult.
Process = Callable[
    [Sequence[str], "str | None", "Mapping[str, str] | None", float], ProcessResult
]

# The runner holds Polaris' own secrets (the Claude bridge token, git token, the
# credentials-vault key, provider API keys, the control-plane DB URL). The process
# this module spawns runs the AI-GENERATED test code, which could read them via
# getenv() and exfiltrate. So the child gets a SCRUBBED copy of the environment:
# these keys (and anything matching a secret-shaped substring, so a future secret is
# caught by default) are stripped. The target reads its OWN `.env.testing` for app
# config, so removing Polaris' secrets never starves the test (ADR: architecture-review
# DO-FIRST #1). Defense in depth alongside the dual-DB guard.
_SECRET_ENV_NAMES = frozenset({"DATABASE_URL", "CLAUDE_BRIDGE_URL"})
_SECRET_ENV_SUBSTRINGS = (
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASSWD",
    "API_KEY",
    "APIKEY",
    "ACCESS_KEY",
    "CREDENTIAL",
    "PRIVATE_KEY",
)


def is_secret_env_key(key: str) -> bool:
    """True if ``key`` names a secret that must not reach a target-test subprocess."""
    upper = key.upper()
    return upper in _SECRET_ENV_NAMES or any(s in upper for s in _SECRET_ENV_SUBSTRINGS)


def scrubbed_environ() -> dict[str, str]:
    """``os.environ`` with Polaris' secrets removed — the safe base for a child that
    executes generated code. Operational vars (PATH, HOME, LANG, …) are preserved."""
    return {k: v for k, v in os.environ.items() if not is_secret_env_key(k)}


def run_process(
    argv: Sequence[str],
    cwd: str | None,
    env: Mapping[str, str] | None,
    timeout: float,
) -> ProcessResult:
    # Scrubbed base (no Polaris secrets) + the caller's explicit overlay (which wins).
    full_env = {**scrubbed_environ(), **(env or {})}
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            env=full_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RunnerTimeout(f"{argv[0]!r} timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise RunnerProcessError(f"executable not found: {argv[0]!r}") from exc
    except OSError as exc:
        raise RunnerProcessError(
            f"failed to run {argv[0]!r}: {type(exc).__name__}"
        ) from exc
    return ProcessResult(completed.returncode, completed.stdout, completed.stderr)
