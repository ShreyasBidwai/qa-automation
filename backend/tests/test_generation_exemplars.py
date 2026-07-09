"""Retrieval-augmented generation (Loop 1, ADR-0070/C4): the generator retrieves THIS
project's own previously-passing tests and feeds them to the renderer as few-shot, so
each run sharpens the next. Same-project only (no cross-tenant code leak)."""

from __future__ import annotations

import uuid

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.plan import plan_cases
from app.generation.render import render_script
from app.ingestion.models import EndpointSpec
from app.models.enums import (
    AuthoredBy,
    Framework,
    OracleSource,
    TestLayer,
    TestType,
)
from app.models.test_case import TestCase
from app.models.test_script import TestScript
from app.repositories.generation_signal_repository import GenerationSignalRepository


def _api_spec() -> EndpointSpec:
    return EndpointSpec(
        method="GET",
        uri="api/orders",
        route_name="orders.index",
        auth_required=False,
        path_params=[],
        query_params=[],
        validation_fields=[],
        is_api=True,
    )


class _CapturingProvider:
    """Duck-typed AIProvider that records the prompt it was handed (tests aren't
    mypy-checked, so a minimal fake is fine)."""

    def __init__(self) -> None:
        self.prompt = ""

    def generate(self, prompt: str, context: object, budget_tokens: int) -> str:
        self.prompt = prompt
        return (
            "<?php\nnamespace Tests\\Feature;\n"
            "class GenTest extends Tests\\TestCase\n{\n"
            "    public function test_x(): void {}\n}\n"
        )


def test_render_script_injects_exemplars_only_when_given() -> None:
    spec = _api_spec()
    case = plan_cases(spec)[0]
    exemplar = "class PriorGoodTest extends Tests\\TestCase { /* proven */ }"

    with_ex = _CapturingProvider()
    render_script(with_ex, spec, case, 4000, exemplars=[exemplar])
    assert "PriorGoodTest" in with_ex.prompt
    assert "previously generated" in with_ex.prompt.lower()

    without_ex = _CapturingProvider()
    render_script(without_ex, spec, case, 4000)
    assert "PriorGoodTest" not in without_ex.prompt


async def test_good_exemplars_returns_only_passing_project_code(
    app_client: tuple[httpx.AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = app_client
    email = f"ex-{uuid.uuid4().hex[:8]}@e.test"
    token = (
        await client.post(
            "/api/v1/auth/signup", json={"email": email, "password": "exampw12345"}
        )
    ).json()["access_token"]
    pid = uuid.UUID(
        (
            await client.post(
                "/api/v1/projects",
                json={"name": "E", "repo_url": "/r"},
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()["id"]
    )

    def _case(layer: TestLayer) -> TestCase:
        return TestCase(
            project_id=pid,
            type=TestType.NEGATIVE,
            layer=layer,
            oracle_source=OracleSource.RULE_DERIVED,
            authored_by=AuthoredBy.AI,
            gen_prompt_version="v1",
            gen_strategy="endpoint",
        )

    good, bad, repaired, web = (
        _case(TestLayer.API),
        _case(TestLayer.API),
        _case(TestLayer.API),
        _case(TestLayer.UI),
    )
    db_session.add_all([good, bad, repaired, web])
    await db_session.flush()
    for case, code in [
        (good, "GOOD_API_CODE"),
        (bad, "BAD_API_CODE"),
        (repaired, "REPAIRED_API_CODE"),
        (web, "WEB_CODE"),
    ]:
        db_session.add(
            TestScript(
                project_id=pid,
                test_case_id=case.id,
                framework=Framework.PEST,
                code=code,
                generated_by="ai",
                deterministic=False,
            )
        )
    await db_session.flush()

    repo = GenerationSignalRepository(db_session)
    run_id = uuid.uuid4()
    await repo.record(
        project_id=pid,
        run_id=run_id,
        test_case_id=good.id,
        prompt_version="v1",
        strategy="endpoint",
        route_class="api",
        outcome="pass",
    )
    await repo.record(
        project_id=pid,
        run_id=run_id,
        test_case_id=bad.id,
        prompt_version="v1",
        strategy="endpoint",
        route_class="api",
        outcome="fail",
    )
    await repo.record(
        project_id=pid,
        run_id=run_id,
        test_case_id=repaired.id,
        prompt_version="v1",
        strategy="endpoint",
        route_class="api",
        outcome="pass",
        repaired=True,
    )
    await repo.record(
        project_id=pid,
        run_id=run_id,
        test_case_id=web.id,
        prompt_version="v1",
        strategy="e2e",
        route_class="web",
        outcome="pass",
    )

    # api exemplars = only the clean first-try pass (fail + repaired excluded).
    assert await repo.good_exemplars(pid, "api") == ["GOOD_API_CODE"]
    # web is a separate corpus.
    assert await repo.good_exemplars(pid, "web") == ["WEB_CODE"]
    # a different project sees none of it (same-project only — no cross-tenant leak).
    assert await repo.good_exemplars(uuid.uuid4(), "api") == []
