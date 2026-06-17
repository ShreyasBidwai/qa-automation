"""AI usage — generate() called per case with budget-capped context; no real model."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.stub import StubAIProvider
from app.ai.types import FailureEvidence, Subgraph, TriageLabel
from app.generation.generator import TestGenerator
from app.generation.plan import plan_cases
from app.generation.render import build_context
from tests.factories import make_project


class _SpyProvider:
    """Wraps the deterministic stub and records every generate() call."""

    def __init__(self) -> None:
        self._stub = StubAIProvider()
        self.calls: list[tuple[str, Subgraph, int]] = []

    def generate(self, prompt: str, context: Subgraph, budget_tokens: int) -> str:
        self.calls.append((prompt, context, budget_tokens))
        return self._stub.generate(prompt, context, budget_tokens)

    def triage(self, failure: FailureEvidence) -> TriageLabel:
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _forbid_real_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("real `claude -p` subprocess invoked in tests")

    monkeypatch.setattr("app.ai.claude_cli.subprocess.run", _boom)


async def test_generate_called_once_per_case_with_budget_capped_context(
    db_session: AsyncSession, endpoint_spec: object
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()

    spy = _SpyProvider()
    generator = TestGenerator(provider=spy, budget_tokens=4096, generated_by="stub")
    cases = plan_cases(endpoint_spec)  # type: ignore[arg-type]

    await generator.generate_and_persist(
        session=db_session, project_id=project.id, spec=endpoint_spec  # type: ignore[arg-type]
    )

    assert len(spy.calls) == len(cases) == 14
    for _prompt, context, budget in spy.calls:
        assert budget == 4096  # the configured budget is passed every call
        rendered = context.render()
        # The deterministic payload + expected status are grounded in the context
        # (so the model assembles around them rather than inventing them).
        assert "payload" in rendered
        assert "expected" in rendered


def test_stub_render_is_deterministic(endpoint_spec: object) -> None:
    stub = StubAIProvider()
    case = plan_cases(endpoint_spec)[0]  # type: ignore[arg-type]
    context = build_context(endpoint_spec, case)  # type: ignore[arg-type]
    first = stub.generate("prompt", context, 1000)
    second = stub.generate("prompt", context, 1000)
    assert first == second
    assert first.strip()
