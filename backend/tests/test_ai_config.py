"""Config-driven provider + model selection (TRD §6)."""

from __future__ import annotations

from typing import Any

import pytest

from app.ai.claude_cli import ClaudeCliProvider
from app.ai.factory import build_ai_provider
from app.ai.gemini import GeminiProvider
from app.ai.stub import StubAIProvider
from app.core.config import Settings


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql+psycopg://u:p@localhost:5432/db"
    }
    values.update(overrides)
    return Settings(**values)


def test_factory_selects_stub_for_tests() -> None:
    provider = build_ai_provider(_settings(ai_provider_mode="stub"))
    assert isinstance(provider, StubAIProvider)


def test_factory_selects_claude_cli_with_configured_model() -> None:
    provider = build_ai_provider(
        _settings(ai_provider_mode="claude_cli", ai_generate_model="claude-opus-4-8")
    )
    assert isinstance(provider, ClaudeCliProvider)
    assert provider._model == "claude-opus-4-8"  # model comes from config


def test_factory_selects_gemini() -> None:
    provider = build_ai_provider(_settings(ai_provider_mode="gemini"))
    assert isinstance(provider, GeminiProvider)


def test_factory_mode_override_wins_over_the_instance_default() -> None:
    # The per-project resolver passes an explicit mode that overrides the env default.
    explicit_gemini = build_ai_provider(
        _settings(ai_provider_mode="claude_cli"), mode="gemini"
    )
    assert isinstance(explicit_gemini, GeminiProvider)
    explicit_stub = build_ai_provider(_settings(ai_provider_mode="gemini"), mode="stub")
    assert isinstance(explicit_stub, StubAIProvider)


def test_factory_rejects_unknown_provider_mode() -> None:
    with pytest.raises(ValueError):
        build_ai_provider(_settings(ai_provider_mode="bogus"))
