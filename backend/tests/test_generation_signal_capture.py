"""Flywheel population (ADR-0070, C2): the execution lifecycle records a GenerationSignal
per AI-generated case, joining its generation version to its outcome; a case with no
gen_prompt_version (human / CSV / legacy) is skipped."""

from __future__ import annotations

import uuid

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.lifecycle import _capture_generation_signals
from app.execution.types import ExecutionResult
from app.models.enums import (
    AuthoredBy,
    OracleSource,
    Outcome,
    RunMode,
    RunTrigger,
    TestLayer,
    TestType,
)
from app.models.generation_signal import GenerationSignal
from app.models.run import Run
from app.models.test_case import TestCase


async def test_lifecycle_captures_generation_signals(
    app_client: tuple[httpx.AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = app_client
    email = f"cap-{uuid.uuid4().hex[:8]}@e.test"
    token = (
        await client.post(
            "/api/v1/auth/signup", json={"email": email, "password": "cappass1234"}
        )
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    pid = uuid.UUID(
        (
            await client.post(
                "/api/v1/projects",
                json={"name": "C", "repo_url": "/r"},
                headers=headers,
            )
        ).json()["id"]
    )

    run = Run(project_id=pid, trigger=RunTrigger.MANUAL, mode=RunMode.B, status="passed")
    db_session.add(run)
    await db_session.flush()

    def _case(layer: TestLayer, version: str | None, strategy: str | None) -> TestCase:
        return TestCase(
            project_id=pid,
            type=TestType.NEGATIVE,
            layer=layer,
            oracle_source=OracleSource.RULE_DERIVED,
            authored_by=AuthoredBy.AI,
            gen_prompt_version=version,
            gen_strategy=strategy,
        )

    ai_api = _case(TestLayer.API, "2026-07-v1", "endpoint")
    ai_ui = _case(TestLayer.UI, "2026-07-v1", "e2e")
    no_version = _case(TestLayer.API, None, None)  # legacy/human — carries no signal
    db_session.add_all([ai_api, ai_ui, no_version])
    await db_session.flush()

    def _result(tc_id: uuid.UUID, outcome: Outcome) -> ExecutionResult:
        return ExecutionResult(
            test_case_id=tc_id,
            script_id=uuid.uuid4(),
            name="t",
            outcome=outcome,
            evidence_ref=None,
        )

    await _capture_generation_signals(
        db_session,
        run,
        [
            _result(ai_api.id, Outcome.PASS),
            _result(ai_ui.id, Outcome.FAIL),
            _result(no_version.id, Outcome.PASS),
        ],
    )

    signals = list(
        (
            await db_session.scalars(
                select(GenerationSignal).where(GenerationSignal.run_id == run.id)
            )
        ).all()
    )
    assert len(signals) == 2  # the no-version case is skipped
    by_case = {signal.test_case_id: signal for signal in signals}
    assert by_case[ai_api.id].outcome == "pass"
    assert by_case[ai_api.id].route_class == "api"
    assert by_case[ai_api.id].prompt_version == "2026-07-v1"
    assert by_case[ai_api.id].strategy == "endpoint"
    assert by_case[ai_ui.id].outcome == "fail"
    assert by_case[ai_ui.id].route_class == "web"
    assert no_version.id not in by_case
