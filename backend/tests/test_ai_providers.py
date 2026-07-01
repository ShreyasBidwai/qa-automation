"""Provider behavior: stub determinism, claude-cli retry/budget, and the
guarantee that NO real `claude -p` is ever invoked in the suite (Standards §15).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from app.ai.budget import estimate_tokens
from app.ai.claude_cli import ClaudeCliProvider, CommandResult
from app.ai.errors import (
    AIInvocationError,
    AITimeout,
    AITransientError,
    BudgetExceeded,
)
from app.ai.stub import StubAIProvider
from app.ai.triage import parse_triage_label, render_failure
from app.ai.types import FailureEvidence, Subgraph, SubgraphNode
from app.core.config import Settings
from app.models.enums import Triage


@pytest.fixture(autouse=True)
def _forbid_real_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    """If any test reaches the real subprocess path, fail loudly."""

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("real `claude -p` subprocess was invoked in tests")

    monkeypatch.setattr("app.ai.claude_cli.subprocess.run", _boom)


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql+psycopg://u:p@localhost:5432/db",
        "ai_max_attempts": 3,
        "ai_retry_base_delay_seconds": 0.0,
        "ai_retry_max_delay_seconds": 0.0,
        "ai_budget_strategy": "truncate",
    }
    values.update(overrides)
    return Settings(**values)


def _noop(_delay: float) -> None:
    return None


def _subgraph() -> Subgraph:
    return Subgraph(nodes=[SubgraphNode(id="n1", kind="endpoint", name="GET /x")])


def test_stub_is_deterministic_and_offline() -> None:
    stub = StubAIProvider()
    subgraph = _subgraph()
    first = stub.generate("prompt A", subgraph, 1000)
    second = stub.generate("prompt A", subgraph, 1000)
    other = stub.generate("prompt B", subgraph, 1000)

    assert first == second  # deterministic
    assert first != other  # input-dependent
    assert first.strip()  # non-empty, valid output
    # The autouse guard guarantees no real `claude -p` ran.


def test_claude_cli_generate_uses_stdin_and_configured_model() -> None:
    captured: dict[str, Any] = {}

    def runner(
        argv: Sequence[str], stdin_text: str, timeout: float
    ) -> CommandResult:
        captured["argv"] = list(argv)
        captured["stdin"] = stdin_text
        return CommandResult(0, "GENERATED TEST CODE", "")

    provider = ClaudeCliProvider(
        _settings(ai_generate_model="claude-opus-4-8"), runner=runner, sleep=_noop
    )
    out = provider.generate("write a smoke test", _subgraph(), 5000)

    assert out == "GENERATED TEST CODE"
    assert captured["argv"][:2] == ["claude", "-p"]
    assert "--model" in captured["argv"]
    assert "claude-opus-4-8" in captured["argv"]
    # Prompt goes via stdin, never argv (no leak to `ps`).
    assert "write a smoke test" in captured["stdin"]
    assert all("write a smoke test" not in arg for arg in captured["argv"])


def _failure(message: str, outcome: str = "fail") -> FailureEvidence:
    return FailureEvidence(test_case_id="c1", outcome=outcome, message=message)


def test_parse_triage_label_bare_prose_and_fallback() -> None:
    # A bare label, any case/separator.
    assert parse_triage_label("real-bug") is Triage.REAL_BUG
    assert parse_triage_label("  REAL_BUG\n") is Triage.REAL_BUG
    assert parse_triage_label("bad test") is Triage.BAD_TEST
    # First label mentioned inside prose wins.
    assert parse_triage_label("This is a flaky timing issue, not a real-bug.") is (
        Triage.FLAKY
    )
    # Unrecognised → unknown, never raises.
    assert parse_triage_label("no idea what happened") is Triage.UNKNOWN
    assert parse_triage_label("") is Triage.UNKNOWN


def test_render_failure_caps_a_giant_trace() -> None:
    rendered = render_failure(_failure("x" * 10_000, outcome="error"))
    assert "outcome: error" in rendered
    assert "truncated" in rendered
    assert len(rendered) < 6000  # capped, so the cheap triage prompt stays cheap


def test_stub_triage_is_deterministic_and_keyword_driven() -> None:
    stub = StubAIProvider()
    assert stub.triage(_failure("Connection refused to the DB")) is Triage.INFRA
    assert stub.triage(_failure("missing Country factory")) is Triage.BAD_TEST
    assert stub.triage(_failure("expected status 201 but got 500")) is Triage.REAL_BUG
    # Same input → same label (offline, no model).
    e = _failure("expected status 201 but got 500")
    assert stub.triage(e) is stub.triage(e)


def test_claude_cli_triage_uses_the_cheap_model_and_parses_the_label() -> None:
    captured: dict[str, Any] = {}

    def runner(
        argv: Sequence[str], stdin_text: str, timeout: float
    ) -> CommandResult:
        captured["argv"] = list(argv)
        captured["stdin"] = stdin_text
        # A real model often answers with prose; parsing must still classify it.
        return CommandResult(
            0, '{"result": "This is a real-bug in the endpoint."}', ""
        )

    provider = ClaudeCliProvider(
        _settings(ai_triage_model="claude-haiku-4-5"), runner=runner, sleep=_noop
    )
    label = provider.triage(_failure("expected 201, got 500"))

    assert label is Triage.REAL_BUG
    # The cheap TRIAGE model is used, not the frontier generate model.
    assert "claude-haiku-4-5" in captured["argv"]
    assert "claude-opus-4-8" not in captured["argv"]
    # The failure message travels via stdin, never argv.
    assert "expected 201, got 500" in captured["stdin"]
    assert all("expected 201, got 500" not in arg for arg in captured["argv"])


def test_claude_cli_retries_transient_then_succeeds() -> None:
    attempts = {"n": 0}

    def runner(
        argv: Sequence[str], stdin_text: str, timeout: float
    ) -> CommandResult:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise AITimeout("transient")
        return CommandResult(0, "ok", "")

    provider = ClaudeCliProvider(_settings(ai_max_attempts=5), runner=runner, sleep=_noop)
    assert provider.generate("p", _subgraph(), 5000) == "ok"
    assert attempts["n"] == 3


def test_claude_cli_nonzero_exit_surfaces_typed_error_after_max_attempts() -> None:
    attempts = {"n": 0}

    def runner(
        argv: Sequence[str], stdin_text: str, timeout: float
    ) -> CommandResult:
        attempts["n"] += 1
        return CommandResult(1, "", "boom")

    provider = ClaudeCliProvider(_settings(ai_max_attempts=3), runner=runner, sleep=_noop)
    with pytest.raises(AITransientError):
        provider.generate("p", _subgraph(), 5000)
    assert attempts["n"] == 3


def test_claude_cli_permanent_error_is_not_retried() -> None:
    attempts = {"n": 0}

    def runner(
        argv: Sequence[str], stdin_text: str, timeout: float
    ) -> CommandResult:
        attempts["n"] += 1
        raise AIInvocationError("cli missing")

    provider = ClaudeCliProvider(_settings(), runner=runner, sleep=_noop)
    with pytest.raises(AIInvocationError):
        provider.generate("p", _subgraph(), 5000)
    assert attempts["n"] == 1


def test_claude_cli_never_sends_over_budget() -> None:
    captured: dict[str, Any] = {}

    def runner(
        argv: Sequence[str], stdin_text: str, timeout: float
    ) -> CommandResult:
        captured["stdin"] = stdin_text
        return CommandResult(0, "ok", "")

    oversized = Subgraph(snippets=["z" * 100_000])
    provider = ClaudeCliProvider(
        _settings(ai_budget_strategy="truncate"), runner=runner, sleep=_noop
    )
    provider.generate("p", oversized, 300)
    assert estimate_tokens(captured["stdin"]) <= 300


def test_claude_cli_budget_raise_never_invokes_runner() -> None:
    attempts = {"n": 0}

    def runner(
        argv: Sequence[str], stdin_text: str, timeout: float
    ) -> CommandResult:
        attempts["n"] += 1
        return CommandResult(0, "ok", "")

    oversized = Subgraph(snippets=["z" * 100_000])
    provider = ClaudeCliProvider(
        _settings(ai_budget_strategy="raise"), runner=runner, sleep=_noop
    )
    with pytest.raises(BudgetExceeded):
        provider.generate("p", oversized, 300)
    assert attempts["n"] == 0  # nothing was ever sent
