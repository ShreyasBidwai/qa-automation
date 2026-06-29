"""Config-driven provider selection (TRD §6).

``claude_cli`` shells to `claude -p`; ``gemini`` calls the Gemini API; ``stub`` is the
deterministic test fake. The mode defaults to ``settings.ai_provider_mode`` but can be
overridden per call — runs resolve it PER PROJECT (project.settings['ai_provider'])
so a project can pick Claude or Gemini from the UI without changing instance config.
"""

from __future__ import annotations

from app.core.config import Settings

from .claude_bridge import make_bridge_runner
from .claude_cli import ClaudeCliProvider
from .gemini import GeminiProvider
from .stub import StubAIProvider
from .types import AIProvider

# The only provider modes the factory will build. Any caller-supplied mode (e.g. a
# value stored on a project) MUST be validated against this before it reaches here.
PROVIDER_MODES = frozenset({"claude_cli", "gemini", "stub"})


def build_ai_provider(settings: Settings, *, mode: str | None = None) -> AIProvider:
    """Build the AI provider for ``mode`` (default ``settings.ai_provider_mode``)."""
    mode = mode or settings.ai_provider_mode
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
    if mode == "gemini":
        return GeminiProvider(settings)
    if mode == "stub":
        return StubAIProvider()
    raise ValueError(
        f"unknown ai_provider_mode {mode!r} (expected one of {sorted(PROVIDER_MODES)})"
    )
