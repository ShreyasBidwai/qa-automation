"""AnthropicApiProvider — the production Claude backend (Messages API), with NO
network and NO real key. The injected ``transport`` stands in for the HTTP call.

Security-critical: the API key travels in the ``x-api-key`` HEADER and NEVER in the
URL; a missing key fails fast without any call; a bad key is fatal (not retried).
Transient (429/529/5xx/connection) failures retry to the cap. Model-tier routing:
generate uses the frontier model, triage the cheap one.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.ai.anthropic_api import AnthropicApiProvider, parse_anthropic_response
from app.ai.errors import AIInvocationError, AITransientError
from app.ai.types import FailureEvidence, Subgraph, SubgraphNode
from app.ai.usage import UsageCollector, install_collector, reset_collector
from app.core.config import Settings
from app.models.enums import Triage


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql+psycopg://u:p@localhost:5432/db",
        "ai_max_attempts": 3,
        "ai_retry_base_delay_seconds": 0.0,
        "ai_retry_max_delay_seconds": 0.0,
        "ai_budget_strategy": "truncate",
        "ai_generate_model": "claude-opus-4-8",
        "ai_triage_model": "claude-haiku-4-5",
        "anthropic_api_key": "sk-ant-test-123",
    }
    values.update(overrides)
    return Settings(**values)


def _noop(_delay: float) -> None:
    return None


def _subgraph() -> Subgraph:
    return Subgraph(nodes=[SubgraphNode(id="n1", kind="endpoint", name="GET /x")])


def _body(text: str, *, input_tokens: int = 11, output_tokens: int = 7) -> str:
    return json.dumps(
        {
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        }
    )


def test_generate_uses_frontier_model_key_in_header_and_records_usage() -> None:
    captured: dict[str, Any] = {}

    def transport(
        url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> tuple[int, str]:
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json.loads(body.decode("utf-8"))
        return 200, _body("GENERATED TEST CODE")

    provider = AnthropicApiProvider(_settings(), transport=transport, sleep=_noop)
    collector = UsageCollector()
    token = install_collector(collector)
    try:
        out = provider.generate("write a smoke test", _subgraph(), 4096)
    finally:
        reset_collector(token)

    assert out == "GENERATED TEST CODE"
    # SECURITY: key in the header, never the URL (which lands in logs).
    assert captured["headers"]["x-api-key"] == "sk-ant-test-123"
    assert "sk-ant-test-123" not in captured["url"]
    assert captured["headers"]["anthropic-version"]
    assert captured["url"].endswith("/messages")
    # Frontier model for generate; the prompt is the user turn's content.
    assert captured["body"]["model"] == "claude-opus-4-8"
    assert "write a smoke test" in captured["body"]["messages"][0]["content"]
    # Usage captured under generation (tokens present; no dollar cost from the API).
    assert len(collector.records) == 1
    usage = collector.records[0].usage
    assert usage.available and usage.input_tokens == 11 and usage.output_tokens == 7
    assert usage.total_cost_usd is None


def test_triage_uses_the_cheap_model_and_records_triage_usage() -> None:
    captured: dict[str, Any] = {}

    def transport(
        url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> tuple[int, str]:
        captured["body"] = json.loads(body.decode("utf-8"))
        return 200, _body("real-bug")

    provider = AnthropicApiProvider(_settings(), transport=transport, sleep=_noop)
    collector = UsageCollector()
    token = install_collector(collector)
    try:
        label = provider.triage(
            FailureEvidence(
                test_case_id="c1", outcome="fail", message="expected 201, got 500"
            )
        )
    finally:
        reset_collector(token)

    assert label is Triage.REAL_BUG
    # The CHEAP triage model is used, not the frontier generate model.
    assert captured["body"]["model"] == "claude-haiku-4-5"
    assert "expected 201, got 500" in captured["body"]["messages"][0]["content"]
    assert collector.records[0].phase == "triage"


def test_missing_key_fails_fast_without_any_call() -> None:
    def transport(*args: Any, **kwargs: Any) -> tuple[int, str]:
        raise AssertionError("must not call the API without a key")

    provider = AnthropicApiProvider(
        _settings(anthropic_api_key=None), transport=transport, sleep=_noop
    )
    with pytest.raises(AIInvocationError):
        provider.generate("x", _subgraph(), 1000)


def test_bad_key_is_fatal_not_retried() -> None:
    calls = 0

    def transport(
        url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> tuple[int, str]:
        nonlocal calls
        calls += 1
        return 401, '{"error": {"message": "invalid x-api-key"}}'

    provider = AnthropicApiProvider(_settings(), transport=transport, sleep=_noop)
    with pytest.raises(AIInvocationError):
        provider.generate("x", _subgraph(), 1000)
    assert calls == 1  # a bad key is not retried


def test_rate_limit_and_overload_are_transient_and_retried() -> None:
    for status in (429, 529, 503):
        calls = 0

        def transport(
            url: str, headers: dict[str, str], body: bytes, timeout: float
        ) -> tuple[int, str]:
            nonlocal calls
            calls += 1
            return status, "{}"  # noqa: B023 — status bound per loop iteration

        provider = AnthropicApiProvider(
            _settings(ai_max_attempts=3), transport=transport, sleep=_noop
        )
        with pytest.raises(AITransientError):
            provider.generate("x", _subgraph(), 1000)
        assert calls == 3  # retried to the cap


def test_parse_response_is_defensive() -> None:
    # Well-formed → text + usage.
    text, usage = parse_anthropic_response(_body("hi", output_tokens=3), model="m")
    assert text == "hi" and usage.available and usage.output_tokens == 3
    # Garbage → empty text + unavailable usage (never raises).
    text, usage = parse_anthropic_response("not json", model="m")
    assert text == "" and not usage.available
