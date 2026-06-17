"""Typed execution errors (Standards §7 — explicit, no bare except, no swallow).

The taxonomy mirrors Standards §7: infra/process failures are retryable, the
dual-DB guard is a loud safety violation, and a malformed evidence artifact is a
parse bug surfaced rather than swallowed.
"""

from __future__ import annotations


class ExecutionError(Exception):
    """Base class for all test-execution failures."""


class RunnerProcessError(ExecutionError):
    """The runner toolchain (e.g. ``pest``) could not be run or failed to spawn."""


class RunnerTimeout(RunnerProcessError):
    """A runner subprocess exceeded its bounded timeout (Standards §12)."""


class JUnitParseError(ExecutionError):
    """A JUnit evidence artifact could not be parsed."""


class ReadOnlyTargetError(ExecutionError):
    """A dual-DB safety violation (Architecture §9).

    Execution targets ONLY the writable, ephemeral test DB. Refusing to proceed
    when handed a read-only/real connection is how we guarantee execution never
    writes to a non-test database.
    """
