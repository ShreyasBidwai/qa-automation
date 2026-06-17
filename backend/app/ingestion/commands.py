"""Injectable subprocess runner (same pattern as the Claude CLI provider, T1.2).

Every external call carries a bounded timeout (Standards §12). The runner is a
plain callable so tests inject a fake and never invoke a live `artisan`/`php`.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .errors import CommandFailed, CommandTimeout, IngestionCommandError


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


# (argv, cwd, timeout_seconds) -> CommandResult. Implementations raise
# CommandTimeout / IngestionCommandError on failure to spawn.
CommandRunner = Callable[[Sequence[str], "str | None", float], CommandResult]


def run_subprocess(
    argv: Sequence[str], cwd: str | None, timeout: float
) -> CommandResult:
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandTimeout(f"command {argv[0]!r} timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise IngestionCommandError(f"executable not found: {argv[0]!r}") from exc
    except OSError as exc:
        raise IngestionCommandError(
            f"failed to run {argv[0]!r}: {type(exc).__name__}"
        ) from exc
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def check_output(result: CommandResult, *, what: str) -> str:
    """Return stdout, or raise CommandFailed on a non-zero exit (no secret leak)."""
    if result.returncode != 0:
        raise CommandFailed(
            f"{what} exited with code {result.returncode}",
            returncode=result.returncode,
        )
    return result.stdout
