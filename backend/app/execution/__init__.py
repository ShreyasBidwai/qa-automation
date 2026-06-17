"""Test execution layer (Architecture §9, TRD §5/§8).

The first ExecutionRunner is the PestRunner: it runs generated Pest scripts
against a bootable Laravel target + a writable, ephemeral test DB inside the
``runners/laravel`` image, and returns framework-agnostic results that the run
lifecycle persists. Dual-DB safety (never write to a read-only/real DB) and
no-leak teardown are enforced here; triage is deferred to Sprint 7.
"""

from __future__ import annotations

from .dual_db import ensure_safe_target, subprocess_db_env
from .errors import (
    ExecutionError,
    JUnitParseError,
    ReadOnlyTargetError,
    RunnerProcessError,
    RunnerTimeout,
)
from .junit import JUnitCase, parse_junit
from .lifecycle import RunLifecycle
from .pest_runner import PestRunner, map_results
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
    "PestRunner",
    "PestScript",
    "ReadOnlyTargetError",
    "RunLifecycle",
    "RunnerProcessError",
    "RunnerTimeout",
    "TargetEnv",
    "ensure_safe_target",
    "map_results",
    "parse_junit",
    "subprocess_db_env",
]
