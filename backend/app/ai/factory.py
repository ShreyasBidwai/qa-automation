"""Config-driven provider selection (TRD §6): dev uses claude -p, tests the stub."""

from __future__ import annotations

from app.core.config import Settings

from .claude_bridge import make_bridge_runner
from .claude_cli import ClaudeCliProvider
from .stub import StubAIProvider
from .types import AIProvider


def build_ai_provider(settings: Settings) -> AIProvider:
    mode = settings.ai_provider_mode
    if mode == "claude_cli":
        # When a bridge URL is configured, `claude -p` runs on the HOST (via the
        # bridge daemon) so the container never touches the host's ~/.claude login;
        # otherwise the CLI runs in-process (single-box dev). Same provider either
        # way — only the injected CommandRunner differs (docs/running-real.md).
        runner = (
            make_bridge_runner(
                settings.claude_bridge_url, settings.claude_bridge_token or ""
            )
            if settings.claude_bridge_url
            else None
        )
        return ClaudeCliProvider(settings, runner=runner)
    if mode == "stub":
        return StubAIProvider()
    raise ValueError(
        f"unknown ai_provider_mode {mode!r} (expected 'claude_cli' or 'stub')"
    )
