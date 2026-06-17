"""Dual-DB safety — execution never reaches a non-test (read-only/real) DB."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

import pytest

from app.execution.dual_db import ensure_safe_target, subprocess_db_env
from app.execution.errors import ReadOnlyTargetError
from app.execution.pest_runner import PestRunner
from app.execution.process import ProcessResult
from app.execution.types import DbHandle, DbRole, PestScript, TargetEnv

_TEST_DB = DbHandle("sqlite::memory:", DbRole.WRITABLE_TEST, ephemeral=True)
_REAL_DB = DbHandle(
    "postgresql://qa:secret@db:5432/prod", DbRole.READ_ONLY_REAL, ephemeral=False
)


def _env(execution_db: DbHandle, **kw: object) -> TargetEnv:
    return TargetEnv(
        app_path="/nonexistent",
        execution_db=execution_db,
        evidence_dir="/nonexistent",
        **kw,  # type: ignore[arg-type]
    )


def test_ensure_safe_target_accepts_writable_ephemeral_test_db() -> None:
    ensure_safe_target(_env(_TEST_DB))  # no raise


def test_ensure_safe_target_rejects_read_only_real_db() -> None:
    with pytest.raises(ReadOnlyTargetError):
        ensure_safe_target(_env(_REAL_DB))


def test_ensure_safe_target_rejects_non_ephemeral_db() -> None:
    durable_test = DbHandle("sqlite:///tmp/x.sqlite", DbRole.WRITABLE_TEST, False)
    with pytest.raises(ReadOnlyTargetError):
        ensure_safe_target(_env(durable_test))


def test_subprocess_env_targets_only_the_sqlite_test_db() -> None:
    env = subprocess_db_env(_TEST_DB)
    assert env["DB_CONNECTION"] == "sqlite"
    assert env["DB_DATABASE"] == ":memory:"
    # Any inherited real connection string is blanked, never forwarded.
    assert env["DATABASE_URL"] == ""
    assert not any("postgres" in v.lower() for v in env.values())


def test_subprocess_env_refuses_to_build_for_a_real_db() -> None:
    with pytest.raises(ReadOnlyTargetError):
        subprocess_db_env(_REAL_DB)


def test_runner_guards_before_spawning_any_process() -> None:
    """A read-only target must be refused BEFORE pest is ever invoked."""
    calls: list[Sequence[str]] = []

    def spy(
        argv: Sequence[str],
        cwd: str | None,
        env: Mapping[str, str] | None,
        timeout: float,
    ) -> ProcessResult:
        calls.append(argv)
        return ProcessResult(0, "", "")

    runner = PestRunner(process=spy)
    script = PestScript(uuid.uuid4(), uuid.uuid4(), "x", "<?php")
    with pytest.raises(ReadOnlyTargetError):
        runner.run([script], _env(_REAL_DB))
    assert calls == []  # never spawned → never touched the DB
