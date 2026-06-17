"""Lightweight data factories for tests (Standards §15).

Unique slugs keep inserts collision-free across tests and parallel workers.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.models.enums import (
    AuthoredBy,
    Framework,
    OracleSource,
    Outcome,
    RunMode,
    RunTrigger,
    TestLayer,
    TestType,
)
from app.models.project import Project
from app.models.result import Result
from app.models.run import Run
from app.models.test_case import TestCase
from app.models.test_script import TestScript


def make_project(**overrides: Any) -> Project:
    attrs: dict[str, Any] = {
        "name": "Test Project",
        "slug": f"test-{uuid.uuid4().hex[:12]}",
    }
    attrs.update(overrides)
    return Project(**attrs)


def make_test_case(project_id: uuid.UUID, **overrides: Any) -> TestCase:
    attrs: dict[str, Any] = {
        "project_id": project_id,
        "type": TestType.SMOKE,
        "layer": TestLayer.API,
        "preconditions": {},
        "steps": [],
        "expected": {},
        "oracle_source": OracleSource.RULE_DERIVED,
        "authored_by": AuthoredBy.AI,
        "status": "draft",
    }
    attrs.update(overrides)
    return TestCase(**attrs)


def make_test_script(
    project_id: uuid.UUID, test_case_id: uuid.UUID, **overrides: Any
) -> TestScript:
    attrs: dict[str, Any] = {
        "project_id": project_id,
        "test_case_id": test_case_id,
        "framework": Framework.PYTEST,
        "code": "def test_placeholder():\n    assert True\n",
        "generated_by": "template",
        "deterministic": True,
    }
    attrs.update(overrides)
    return TestScript(**attrs)


def make_run(project_id: uuid.UUID, **overrides: Any) -> Run:
    attrs: dict[str, Any] = {
        "project_id": project_id,
        "trigger": RunTrigger.MANUAL,
        "mode": RunMode.C,
        "status": "pending",
    }
    attrs.update(overrides)
    return Run(**attrs)


def make_result(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    test_case_id: uuid.UUID,
    **overrides: Any,
) -> Result:
    attrs: dict[str, Any] = {
        "project_id": project_id,
        "run_id": run_id,
        "test_case_id": test_case_id,
        "outcome": Outcome.PASS,
    }
    attrs.update(overrides)
    return Result(**attrs)
