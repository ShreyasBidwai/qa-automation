"""Config-driven provider selection (TRD §6): dev uses claude -p, tests the stub."""

from __future__ import annotations

from app.core.config import Settings

from .claude_cli import ClaudeCliProvider
from .stub import StubAIProvider
from .types import AIProvider


def build_ai_provider(settings: Settings) -> AIProvider:
    mode = settings.ai_provider_mode
    if mode == "claude_cli":
        return ClaudeCliProvider(settings)
    if mode == "stub":
        return StubAIProvider()
    raise ValueError(
        f"unknown ai_provider_mode {mode!r} (expected 'claude_cli' or 'stub')"
    )
