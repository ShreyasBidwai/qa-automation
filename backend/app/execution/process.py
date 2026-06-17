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


def run_process(
    argv: Sequence[str],
    cwd: str | None,
    env: Mapping[str, str] | None,
    timeout: float,
) -> ProcessResult:
    full_env = {**os.environ, **(env or {})}
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
