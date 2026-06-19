"""Mode C step 1 — NL → TestIntent (fast; StubAIProvider + a JSON provider)."""

from __future__ import annotations

import pytest

from app.ai.stub import StubAIProvider
from app.ai.types import FailureEvidence, Subgraph, TriageLabel
from app.generation.nl_intent import (
    IntentError,
    ScenarioType,
    parse_test_intent,
)


class _JsonProvider:
    """A provider that returns a fixed (intent) string — to exercise the AI path."""

    def __init__(self, payload: str) -> None:
        self._payload = payload

    def generate(self, prompt: str, context: Subgraph, budget_tokens: int) -> str:
        return self._payload

    def triage(self, failure: FailureEvidence) -> TriageLabel:  # pragma: no cover
        raise NotImplementedError


def test_intent_falls_back_to_nl_when_provider_is_unstructured() -> None:
    # The StubAIProvider returns a fingerprint comment (no JSON) → deterministic
    # extraction from the request itself.
    intent = parse_test_intent(StubAIProvider(), "test the checkout flow")
    assert "checkout" in intent.keywords
    assert "test" not in intent.keywords  # stop-words dropped
    assert "the" not in intent.keywords
    assert intent.scenario_type is ScenarioType.JOURNEY  # "checkout"/"flow" hints


def test_intent_uses_ai_json_when_present() -> None:
    provider = _JsonProvider(
        '{"keywords": ["login", "password"], "scenario_type": "negative"}'
    )
    intent = parse_test_intent(provider, "log in with a bad password")
    assert intent.keywords == ("login", "password")
    assert intent.scenario_type is ScenarioType.NEGATIVE


def test_invalid_ai_scenario_falls_back_to_deterministic_inference() -> None:
    provider = _JsonProvider('{"keywords": ["dashboard"], "scenario_type": "bogus"}')
    intent = parse_test_intent(provider, "the dashboard loads")
    assert intent.keywords == ("dashboard",)
    assert intent.scenario_type is ScenarioType.SMOKE  # "loads" hint


def test_negative_hint_classification_from_nl() -> None:
    intent = parse_test_intent(StubAIProvider(), "submit an invalid email")
    assert intent.scenario_type is ScenarioType.NEGATIVE
    assert "invalid" in intent.keywords


def test_default_scenario_is_happy_path_when_no_hints() -> None:
    intent = parse_test_intent(StubAIProvider(), "create a user account")
    assert intent.scenario_type is ScenarioType.HAPPY_PATH
    assert "account" in intent.keywords


def test_malformed_json_falls_back_to_nl_extraction() -> None:
    intent = parse_test_intent(_JsonProvider("{not valid json}"), "the orders page")
    assert intent.keywords == ("orders", "page")


def test_request_with_only_stopwords_raises() -> None:
    with pytest.raises(IntentError):
        parse_test_intent(StubAIProvider(), "test the a an")


def test_empty_request_raises() -> None:
    with pytest.raises(IntentError):
        parse_test_intent(StubAIProvider(), "   ")
