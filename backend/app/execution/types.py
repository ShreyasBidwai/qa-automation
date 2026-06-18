"""Execution-layer value objects and the ExecutionRunner contract (TRD §5).

A runner runs inside its own per-stack container (Architecture §9), so it never
touches the control-plane DB: ``run()`` returns framework-agnostic
``ExecutionResult`` value objects that the run lifecycle (lifecycle.py) persists
as ``results`` rows.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.models.enums import Outcome


class DbRole(str, enum.Enum):
    """Which side of the dual-DB rule a connection is (Architecture §9)."""

    WRITABLE_TEST = "writable-test"  # ephemeral, throwaway — the only write target
    READ_ONLY_REAL = "read-only-real"  # introspection/reference only — never written


@dataclass(frozen=True)
class DbHandle:
    url: str
    role: DbRole
    ephemeral: bool


@dataclass(frozen=True)
class TargetEnv:
    """Where and against what a runner executes.

    ``execution_db`` MUST be the writable, ephemeral test DB; ``introspection_db``
    (Sprint 2) is read-only and never written here. ``base_url`` is the running
    target frontend a browser runner (PlaywrightRunner) drives; it is unused by
    process/file runners like the PestRunner. The dual-DB guard still applies to
    browser runners: ``execution_db`` asserts the target environment is a
    throwaway test environment (the app behind ``base_url`` must be test-backed),
    even though the browser never opens the DB itself.
    """

    app_path: str
    execution_db: DbHandle
    evidence_dir: str
    introspection_db: DbHandle | None = None
    base_url: str | None = None


@dataclass(frozen=True)
class PestScript:
    """A generated test script to execute, tied back to its case/script rows."""

    test_case_id: uuid.UUID
    script_id: uuid.UUID
    name: str  # unique slug → the test file stem; how results map back
    code: str


@dataclass(frozen=True)
class ExecutionResult:
    """One test's outcome, framework-agnostic — persisted as a ``results`` row."""

    test_case_id: uuid.UUID
    script_id: uuid.UUID
    name: str
    outcome: Outcome
    evidence_ref: str | None
    message: str | None = None


@runtime_checkable
class ExecutionRunner(Protocol):
    """TRD §5 contract. ``teardown`` is the Standards §11 no-leak hook."""

    framework: str

    def run(
        self, scripts: list[PestScript], target_env: TargetEnv
    ) -> list[ExecutionResult]: ...

    def teardown(self, target_env: TargetEnv) -> None: ...
