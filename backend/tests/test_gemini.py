"""GeminiProvider — budget/retry/usage/parse + the security guarantees, with NO
network and NO real key. The injected ``transport`` stands in for the HTTP call.

The security-critical assertions: the API key travels in the ``x-goog-api-key``
HEADER and NEVER in the URL; a missing key fails fast without any call; a bad key is
fatal (not retried). Transient (429/5xx/connection) failures retry to the cap.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.ai.errors import AIInvocationError, AITransientError
from app.ai.gemini import GeminiProvider, parse_gemini_response
from app.ai.types import Subgraph, SubgraphNode
from app.ai.usage import UsageCollector, install_collector, reset_collector
from app.core.config import Settings


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql+psycopg://u:p@localhost:5432/db",
        "ai_max_attempts": 3,
        "ai_retry_base_delay_seconds": 0.0,
        "ai_retry_max_delay_seconds": 0.0,
        "ai_budget_strategy": "truncate",
        "gemini_api_key": "test-key-123",
        "gemini_generate_model": "gemini-2.5-flash",
    }
    values.update(overrides)
    return Settings(**values)


def _noop(_delay: float) -> None:
    return None


def _subgraph() -> Subgraph:
    return Subgraph(nodes=[SubgraphNode(id="n1", kind="endpoint", name="GET /x")])


_OK_BODY = json.dumps(
    {
        "candidates": [{"content": {"parts": [{"text": "GENERATED"}]}}],
        "usageMetadata": {
            "promptTokenCount": 11,
            "candidatesTokenCount": 7,
            "totalTokenCount": 18,
        },
    }
)


def test_generate_succeeds_keeps_key_in_header_and_records_usage() -> None:
    captured: dict[str, Any] = {}

    def transport(
        url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> tuple[int, str]:
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json.loads(body.decode("utf-8"))
        return 200, _OK_BODY

    provider = GeminiProvider(_settings(), transport=transport, sleep=_noop)
    collector = UsageCollector()
    token = install_collector(collector)
    try:
        out = provider.generate("the prompt", _subgraph(), 4096)
    finally:
        reset_collector(token)

    assert out == "GENERATED"
    # SECURITY: the key is in the header, never the URL (which lands in logs).
    assert captured["headers"]["x-goog-api-key"] == "test-key-123"
    assert "test-key-123" not in captured["url"]
    assert captured["url"].endswith("/models/gemini-2.5-flash:generateContent")
    # The assembled prompt is the single user turn's text.
    assert "the prompt" in captured["body"]["contents"][0]["parts"][0]["text"]
    # Usage captured (tokens from usageMetadata; Gemini gives no dollar cost).
    assert len(collector.records) == 1
    usage = collector.records[0].usage
    assert usage.available and usage.input_tokens == 11 and usage.output_tokens == 7
    assert usage.total_cost_usd is None


def test_missing_key_fails_fast_without_any_call() -> None:
    def transport(*args: Any, **kwargs: Any) -> tuple[int, str]:
        raise AssertionError("must not call the API without a key")

    provider = GeminiProvider(
        _settings(gemini_api_key=None), transport=transport, sleep=_noop
    )
    with pytest.raises(AIInvocationError, match="GEMINI_API_KEY"):
        provider.generate("p", _subgraph(), 1024)


def test_bad_key_is_fatal_not_retried() -> None:
    calls = {"n": 0}

    def transport(
        url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> tuple[int, str]:
        calls["n"] += 1
        return 401, '{"error":{"message":"API key not valid"}}'

    provider = GeminiProvider(_settings(), transport=transport, sleep=_noop)
    with pytest.raises(AIInvocationError, match="key"):
        provider.generate("p", _subgraph(), 1024)
    assert calls["n"] == 1  # a fatal error is not retried


def test_rate_limit_is_transient_and_retried_to_the_cap() -> None:
    calls = {"n": 0}

    def transport(
        url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> tuple[int, str]:
        calls["n"] += 1
        return 429, "rate limited"

    provider = GeminiProvider(
        _settings(ai_max_attempts=3), transport=transport, sleep=_noop
    )
    with pytest.raises(AITransientError):
        provider.generate("p", _subgraph(), 1024)
    assert calls["n"] == 3  # retried up to the configured cap


def test_connection_error_is_transient() -> None:
    def transport(
        url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> tuple[int, str]:
        raise OSError("connection refused")

    provider = GeminiProvider(
        _settings(ai_max_attempts=1), transport=transport, sleep=_noop
    )
    with pytest.raises(AITransientError, match="unreachable"):
        provider.generate("p", _subgraph(), 1024)


def test_empty_output_is_transient() -> None:
    def transport(
        url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> tuple[int, str]:
        return 200, json.dumps({"candidates": [], "usageMetadata": {}})

    provider = GeminiProvider(
        _settings(ai_max_attempts=1), transport=transport, sleep=_noop
    )
    with pytest.raises(AITransientError, match="empty"):
        provider.generate("p", _subgraph(), 1024)


# --- parse_gemini_response (pure, never raises) ------------------------------


def test_parse_valid_response() -> None:
    text, usage = parse_gemini_response(_OK_BODY, model="gemini-2.5-flash")
    assert text == "GENERATED"
    assert usage.available and usage.input_tokens == 11 and usage.output_tokens == 7


def test_parse_malformed_json_is_unavailable() -> None:
    text, usage = parse_gemini_response("not json at all", model="m")
    assert text == "" and not usage.available


def test_parse_missing_usage_keeps_text_but_flags_unavailable() -> None:
    body = json.dumps({"candidates": [{"content": {"parts": [{"text": "X"}]}}]})
    text, usage = parse_gemini_response(body, model="m")
    assert text == "X" and not usage.available
