"""Gemini rate-limit-aware model fallback (generation path) — with a MOCK transport
and a MOCK clock/sleep: NO network, NO real key, NO real sleep.

A 429 RESOURCE_EXHAUSTED is per-minute OR per-day depending ONLY on the response
body, which is parsed (never a hardcoded quota number). Per-minute → wait (honoring
the API's RetryInfo) + retry the SAME model, bounded; per-day → advance to the NEXT
model; whole chain day-exhausted → a clear terminal error, never a hang. The
single-model happy path is unchanged, and the runtime default transport stays REAL.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.ai.errors import AITransientError, AllModelsExhausted
from app.ai.factory import build_ai_provider
from app.ai.gemini import (
    DayExhaustionRegistry,
    GeminiProvider,
    QuotaScope,
    _next_utc_midnight,
    _urllib_transport,
    classify_quota_failure,
)
from app.ai.types import Subgraph, SubgraphNode
from app.core.config import Settings

_FIXED_NOW = 1_700_000_000.0  # a stable epoch (no real clock) — 2023-11-14T22:13:20Z

# Representative free-tier quotaIds (substring is what classification keys on).
_MINUTE_QUOTA = "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
_DAY_QUOTA = "GenerateRequestsPerDayPerProjectPerModel-FreeTier"

_OK_BODY = json.dumps(
    {
        "candidates": [{"content": {"parts": [{"text": "GENERATED"}]}}],
        "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 3},
    }
)


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


def _subgraph() -> Subgraph:
    return Subgraph(nodes=[SubgraphNode(id="n1", kind="endpoint", name="GET /x")])


def _quota_429(quota_id: str, *, retry_delay: str | None = None) -> str:
    """A realistic Gemini 429 RESOURCE_EXHAUSTED body for ``quota_id``."""
    details: list[dict[str, Any]] = [
        {
            "@type": "type.googleapis.com/google.rpc.QuotaFailure",
            "violations": [
                {
                    "quotaId": quota_id,
                    "quotaMetric": "generativelanguage.googleapis.com/generate_content",
                }
            ],
        }
    ]
    if retry_delay is not None:
        details.append(
            {
                "@type": "type.googleapis.com/google.rpc.RetryInfo",
                "retryDelay": retry_delay,
            }
        )
    return json.dumps(
        {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": details}}
    )


class _SleepSpy:
    """Records sleep durations instead of sleeping (mock clock — no real wait)."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, delay: float) -> None:
        self.delays.append(delay)


class _ScriptedTransport:
    """Returns scripted ``(status, body)`` per model, identified from the URL.

    ``script`` maps model → list of responses; the LAST entry is sticky (repeats), so
    ``[r]`` means "always r" and ``[a, b]`` means "a once, then b forever". Records
    the ordered list of models actually called.
    """

    def __init__(self, script: dict[str, list[tuple[int, str]]]) -> None:
        self._script = {m: list(rs) for m, rs in script.items()}
        self.calls: list[str] = []

    def __call__(
        self, url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> tuple[int, str]:
        model = url.rsplit("/models/", 1)[1].split(":", 1)[0]
        self.calls.append(model)
        queue = self._script[model]
        return queue.pop(0) if len(queue) > 1 else queue[0]


# --- classification (pure) ---------------------------------------------------


def test_classify_per_minute_quota_is_minute() -> None:
    scope, delay = classify_quota_failure(_quota_429(_MINUTE_QUOTA))
    assert scope is QuotaScope.MINUTE
    assert delay is None


def test_classify_per_day_quota_is_day() -> None:
    scope, _ = classify_quota_failure(_quota_429(_DAY_QUOTA))
    assert scope is QuotaScope.DAY  # this model is done until midnight


def test_classify_429_without_quota_failure_is_conservatively_minute() -> None:
    # No parseable QuotaFailure → MINUTE (never burn a model on an unconfirmed signal).
    assert classify_quota_failure('{"error":{"code":429}}')[0] is QuotaScope.MINUTE
    assert classify_quota_failure("rate limited, not even json")[0] is QuotaScope.MINUTE


def test_classify_parses_retry_info_delay() -> None:
    scope, delay = classify_quota_failure(_quota_429(_MINUTE_QUOTA, retry_delay="15s"))
    assert scope is QuotaScope.MINUTE
    assert delay == 15.0


# --- per-minute: wait (honor RetryInfo) + retry SAME model, then succeed ------


def test_minute_429_waits_then_retries_same_model_and_succeeds() -> None:
    transport = _ScriptedTransport(
        {
            "gemini-2.5-flash": [
                (429, _quota_429(_MINUTE_QUOTA, retry_delay="20s")),
                (200, _OK_BODY),
            ]
        }
    )
    sleep = _SleepSpy()
    provider = GeminiProvider(
        _settings(),
        transport=transport,
        sleep=sleep,
        day_registry=DayExhaustionRegistry(),
    )

    out = provider.generate("p", _subgraph(), 1024)

    assert out == "GENERATED"
    assert transport.calls == ["gemini-2.5-flash", "gemini-2.5-flash"]  # SAME model
    assert 20.0 in sleep.delays  # honored RetryInfo.retryDelay (no real sleep happened)


def test_minute_429_without_retry_info_waits_the_capped_default() -> None:
    transport = _ScriptedTransport(
        {"gemini-2.5-flash": [(429, _quota_429(_MINUTE_QUOTA)), (200, _OK_BODY)]}
    )
    sleep = _SleepSpy()
    provider = GeminiProvider(
        _settings(gemini_minute_retry_cap_seconds=42.0),
        transport=transport,
        sleep=sleep,
        day_registry=DayExhaustionRegistry(),
    )

    assert provider.generate("p", _subgraph(), 1024) == "GENERATED"
    assert 42.0 in sleep.delays  # default cap used when the 429 carries no RetryInfo


# --- per-day: advance to the NEXT model --------------------------------------


def test_day_429_advances_to_next_model_and_succeeds() -> None:
    registry = DayExhaustionRegistry()
    transport = _ScriptedTransport(
        {
            "gemini-2.5-flash": [(429, _quota_429(_DAY_QUOTA))],
            "gemini-2.0-flash": [(200, _OK_BODY)],
        }
    )
    provider = GeminiProvider(
        _settings(gemini_model_chain="gemini-2.5-flash,gemini-2.0-flash"),
        transport=transport,
        sleep=_SleepSpy(),
        clock=lambda: _FIXED_NOW,
        day_registry=registry,
    )

    out = provider.generate("p", _subgraph(), 1024)

    assert out == "GENERATED"
    assert transport.calls == ["gemini-2.5-flash", "gemini-2.0-flash"]  # advanced
    assert registry.is_exhausted("gemini-2.5-flash", _FIXED_NOW)  # marked, not retried
    assert not registry.is_exhausted("gemini-2.0-flash", _FIXED_NOW)


def test_day_429_does_not_retry_the_exhausted_model() -> None:
    # A per-day 429 is NOT retried on the same model (unlike a per-minute one).
    transport = _ScriptedTransport(
        {
            "a": [(429, _quota_429(_DAY_QUOTA))],
            "b": [(200, _OK_BODY)],
        }
    )
    provider = GeminiProvider(
        _settings(gemini_model_chain="a,b"),
        transport=transport,
        sleep=_SleepSpy(),
        clock=lambda: _FIXED_NOW,
        day_registry=DayExhaustionRegistry(),
    )
    provider.generate("p", _subgraph(), 1024)
    assert transport.calls.count("a") == 1  # one call, then advance — no retry


# --- whole chain day-exhausted: clear terminal error, no hang ----------------


def test_all_models_day_exhausted_raises_terminal_error() -> None:
    transport = _ScriptedTransport(
        {
            "a": [(429, _quota_429(_DAY_QUOTA))],
            "b": [(429, _quota_429(_DAY_QUOTA))],
        }
    )
    provider = GeminiProvider(
        _settings(gemini_model_chain="a,b"),
        transport=transport,
        sleep=_SleepSpy(),
        clock=lambda: _FIXED_NOW,
        day_registry=DayExhaustionRegistry(),
    )

    with pytest.raises(AllModelsExhausted) as excinfo:
        provider.generate("p", _subgraph(), 1024)

    assert excinfo.value.models == ["a", "b"]
    assert transport.calls == ["a", "b"]  # one call each — bounded, no hang


def test_already_day_exhausted_models_are_skipped_without_a_call() -> None:
    registry = DayExhaustionRegistry()
    registry.mark("a", _FIXED_NOW)  # pre-exhausted (e.g. a prior run hit the day cap)
    transport = _ScriptedTransport({"b": [(200, _OK_BODY)]})
    provider = GeminiProvider(
        _settings(gemini_model_chain="a,b"),
        transport=transport,
        sleep=_SleepSpy(),
        clock=lambda: _FIXED_NOW,
        day_registry=registry,
    )

    assert provider.generate("p", _subgraph(), 1024) == "GENERATED"
    assert transport.calls == ["b"]  # 'a' never called — skipped as day-exhausted


# --- per-minute bound: never an unbounded wait loop --------------------------


def test_minute_wait_bound_is_respected_then_gives_up() -> None:
    transport = _ScriptedTransport(
        {"gemini-2.5-flash": [(429, _quota_429(_MINUTE_QUOTA))]}
    )
    provider = GeminiProvider(
        _settings(gemini_max_minute_retries=2),
        transport=transport,
        sleep=_SleepSpy(),
        day_registry=DayExhaustionRegistry(),
    )

    with pytest.raises(AITransientError, match="per-minute quota"):
        provider.generate("p", _subgraph(), 1024)
    assert transport.calls == ["gemini-2.5-flash"] * 2  # exactly the bound, no more


def test_minute_giveup_on_one_model_advances_to_the_next() -> None:
    # The first model never clears its per-minute quota (bound=2); fall through to the
    # second, which succeeds. Minute give-up is transient, so the chain still advances.
    transport = _ScriptedTransport(
        {
            "a": [(429, _quota_429(_MINUTE_QUOTA))],
            "b": [(200, _OK_BODY)],
        }
    )
    provider = GeminiProvider(
        _settings(gemini_model_chain="a,b", gemini_max_minute_retries=2),
        transport=transport,
        sleep=_SleepSpy(),
        day_registry=DayExhaustionRegistry(),
    )

    assert provider.generate("p", _subgraph(), 1024) == "GENERATED"
    assert transport.calls == ["a", "a", "b"]  # two bounded waits on 'a', then 'b'


# --- regression: single-model happy path unchanged ---------------------------


def test_single_model_happy_path_unchanged() -> None:
    transport = _ScriptedTransport({"gemini-2.5-flash": [(200, _OK_BODY)]})
    provider = GeminiProvider(
        _settings(),
        transport=transport,
        sleep=_SleepSpy(),
        day_registry=DayExhaustionRegistry(),
    )
    assert provider.generate("p", _subgraph(), 1024) == "GENERATED"
    assert transport.calls == ["gemini-2.5-flash"]  # one model, one call


def test_empty_chain_config_falls_back_to_single_generate_model() -> None:
    provider = GeminiProvider(
        _settings(gemini_model_chain="   "),  # blank → one-element chain
        transport=_ScriptedTransport({"gemini-2.5-flash": [(200, _OK_BODY)]}),
        sleep=_SleepSpy(),
        day_registry=DayExhaustionRegistry(),
    )
    assert provider.generate("p", _subgraph(), 1024) == "GENERATED"


# --- day-exhaustion registry reset (next UTC midnight) -----------------------


def test_day_exhaustion_resets_after_utc_midnight() -> None:
    registry = DayExhaustionRegistry()
    registry.mark("m", _FIXED_NOW)
    assert registry.is_exhausted("m", _FIXED_NOW)  # still exhausted now
    reset = _next_utc_midnight(_FIXED_NOW)
    assert registry.is_exhausted("m", reset - 1)  # just before the window rolls over
    assert not registry.is_exhausted("m", reset)  # at/after midnight → cleared


# --- Part B guard: the runtime default transport is REAL, never a stub --------


def test_real_transport_is_the_default_for_the_runtime_path() -> None:
    # Constructed with no transport override (the runtime path), the provider uses the
    # real urllib transport — selecting gemini does NOT silently fall back to a stub.
    provider = GeminiProvider(_settings())
    assert provider._transport is _urllib_transport


def test_factory_builds_gemini_with_the_real_transport() -> None:
    provider = build_ai_provider(_settings(ai_provider_mode="gemini"), mode="gemini")
    assert isinstance(provider, GeminiProvider)
    assert provider._transport is _urllib_transport
