"""Test execution layer (Architecture §9, TRD §5/§8).

The first ExecutionRunner is the PhpTestRunner: it runs generated PHP test scripts
against a bootable Laravel target + a writable, ephemeral test DB inside the
``runners/laravel`` image, detecting whichever test binary the target ships (Pest
or PHPUnit), and returns framework-agnostic results that the run lifecycle
persists. Dual-DB safety (never write to a read-only/real DB) and no-leak teardown
are enforced here; triage is deferred to Sprint 7.
"""

from __future__ import annotations

from .dual_db import ensure_safe_target, subprocess_db_env
from .errors import (
    ExecutionError,
    JUnitParseError,
    MissingTargetUrlError,
    PlaywrightReportError,
    ReadOnlyTargetError,
    RunnerProcessError,
    RunnerTimeout,
)
from .junit import JUnitCase, parse_junit
from .lifecycle import RunLifecycle
from .php_test_runner import (
    PestRunner,
    PhpTestRunner,
    detect_test_binary,
    map_results,
)
from .playwright_report import PlaywrightCase, parse_playwright_json
from .playwright_runner import PlaywrightRunner
from .types import (
    DbHandle,
    DbRole,
    ExecutionResult,
    ExecutionRunner,
    PestScript,
    TargetEnv,
)

__all__ = [
    "DbHandle",
    "DbRole",
    "ExecutionError",
    "ExecutionResult",
    "ExecutionRunner",
    "JUnitCase",
    "JUnitParseError",
    "MissingTargetUrlError",
    "PestRunner",
    "PestScript",
    "PhpTestRunner",
    "PlaywrightCase",
    "PlaywrightReportError",
    "PlaywrightRunner",
    "ReadOnlyTargetError",
    "RunLifecycle",
    "RunnerProcessError",
    "RunnerTimeout",
    "TargetEnv",
    "detect_test_binary",
    "ensure_safe_target",
    "map_results",
    "parse_junit",
    "parse_playwright_json",
    "subprocess_db_env",
]
