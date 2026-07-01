"""Anthropic Messages API provider — the PRODUCTION AIProvider backend (TRD §6).

Calls Anthropic's ``/v1/messages`` endpoint over HTTPS directly, so production does
not depend on the interactive ``claude`` CLI (a dev seam). Mirrors
:class:`~app.ai.gemini.GeminiProvider`: it enforces the same token budget, applies a
timeout, retries transient failures with bounded backoff + jitter, and records usage
— so it is interchangeable behind ``AIProvider`` and chosen per project.

Model-tier routing: ``generate`` uses the frontier ``ai_generate_model`` and
``triage`` the cheap ``ai_triage_model`` — the same knobs the CLI provider reads, so
the tiering is provider-agnostic and config-driven.

Security: the API key is a SECRET. It comes from the environment ONLY
(``ANTHROPIC_API_KEY``), is sent via the ``x-api-key`` HEADER (never the URL — a key
in a URL leaks into logs/proxies/history), and is never logged, returned, or stored.
No prompt, context, or output text is logged. The HTTP call is injected as a
``Transport`` so tests exercise budget/retry/timeout/parse without any network — the
DEFAULT transport is the real one, so the runtime path makes a real call once a key
is supplied.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from app.core.config import Settings

from .budget import BudgetStrategy, PromptParts, build_within_budget, estimate_tokens
from .errors import AIInvocationError, AITimeout, AITransientError
from .prompts import GENERATE_INSTRUCTION, TRIAGE_INSTRUCTION
from .retry import with_retries
from .triage import parse_triage_label, render_failure
from .types import FailureEvidence, Subgraph, TriageLabel
from .usage import PHASE_GENERATION, PHASE_TRIAGE, CliUsage, record_usage

logger = logging.getLogger("app.ai")

_ANTHROPIC_VERSION = "2023-06-01"
# Triage prompts are tiny and the reply is a single label; a small output cap + small
# budget keep the cheap-tier call cheap (build_within_budget trims a giant trace).
_TRIAGE_BUDGET_TOKENS = 8000
_TRIAGE_MAX_OUTPUT_TOKENS = 32

# (url, headers, body, timeout) -> (status_code, response_text).
# Implementations raise AITimeout on a read timeout and OSError on connect failure.
Transport = Callable[[str, dict[str, str], bytes, float], "tuple[int, str]"]


def _urllib_transport(
    url: str, headers: dict[str, str], body: bytes, timeout: float
) -> tuple[int, str]:
    """Default sync HTTP POST via stdlib urllib (no extra dependency)."""
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # An HTTP error response still carries a status + a body worth classifying.
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except TimeoutError as exc:
        raise AITimeout(f"anthropic API timed out after {timeout}s") from exc


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_anthropic_response(body: str, *, model: str | None) -> tuple[str, CliUsage]:
    """Parse a ``/v1/messages`` response → (output_text, usage). NEVER raises.

    Concatenates the text blocks of ``content``; reads ``usage`` for the token counts
    (the Messages API returns no dollar figure, so ``total_cost_usd`` stays null).
    Malformed output falls back to empty text + unavailable usage, which the caller
    treats as a transient empty result.
    """
    try:
        envelope = json.loads(body)
    except (json.JSONDecodeError, ValueError, TypeError):
        return "", CliUsage.unavailable(model=model)
    if not isinstance(envelope, dict):
        return "", CliUsage.unavailable(model=model)

    text = ""
    content = envelope.get("content")
    if isinstance(content, list):
        text = "".join(
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        )

    usage = envelope.get("usage")
    if not isinstance(usage, dict):
        return text, CliUsage.unavailable(model=model)
    return text, CliUsage(
        available=True,
        model=model,
        input_tokens=_as_int(usage.get("input_tokens")),
        output_tokens=_as_int(usage.get("output_tokens")),
        cache_creation_input_tokens=_as_int(usage.get("cache_creation_input_tokens")),
        cache_read_input_tokens=_as_int(usage.get("cache_read_input_tokens")),
        total_cost_usd=None,
    )


class AnthropicApiProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = settings.anthropic_api_key or ""
        self._base_url = settings.anthropic_base_url.rstrip("/")
        self._version = settings.anthropic_version or _ANTHROPIC_VERSION
        self._generate_model = settings.ai_generate_model
        self._triage_model = settings.ai_triage_model
        self._max_output = settings.anthropic_max_output_tokens
        self._timeout = settings.ai_timeout_seconds
        self._max_attempts = settings.ai_max_attempts
        self._base_delay = settings.ai_retry_base_delay_seconds
        self._max_delay = settings.ai_retry_max_delay_seconds
        self._strategy = BudgetStrategy(settings.ai_budget_strategy)
        # The DEFAULT is the REAL HTTP transport; a fake is injected only by tests.
        self._transport = transport or _urllib_transport
        self._sleep = sleep

    def generate(self, prompt: str, context: Subgraph, budget_tokens: int) -> str:
        self._require_key()
        parts = PromptParts(
            instruction=GENERATE_INSTRUCTION,
            user_prompt=prompt,
            context_text=context.render(),
        )
        assembled = build_within_budget(parts, budget_tokens, strategy=self._strategy)
        logger.info(
            "ai.generate.start",
            extra={
                "model": self._generate_model,
                "estimated_tokens": estimate_tokens(assembled),
                "budget_tokens": budget_tokens,
            },
        )
        output = with_retries(
            lambda: self._invoke(
                self._generate_model,
                assembled,
                phase=PHASE_GENERATION,
                max_tokens=self._max_output,
            ),
            max_attempts=self._max_attempts,
            base_delay=self._base_delay,
            max_delay=self._max_delay,
            retry_on=(AITimeout, AITransientError),
            sleep=self._sleep,
        )
        logger.info("ai.generate.ok", extra={"model": self._generate_model})
        return output

    def triage(self, failure: FailureEvidence) -> TriageLabel:
        """Classify a failing result on the cheap tier (ai_triage_model, ADR-0049)."""
        self._require_key()
        parts = PromptParts(
            instruction=TRIAGE_INSTRUCTION,
            user_prompt=render_failure(failure),
            context_text="",
        )
        assembled = build_within_budget(
            parts, _TRIAGE_BUDGET_TOKENS, strategy=self._strategy
        )
        output = with_retries(
            lambda: self._invoke(
                self._triage_model,
                assembled,
                phase=PHASE_TRIAGE,
                max_tokens=_TRIAGE_MAX_OUTPUT_TOKENS,
            ),
            max_attempts=self._max_attempts,
            base_delay=self._base_delay,
            max_delay=self._max_delay,
            retry_on=(AITimeout, AITransientError),
            sleep=self._sleep,
        )
        return parse_triage_label(output)

    def _require_key(self) -> None:
        if not self._api_key:
            # A config error, not transient — fail fast and clearly (don't retry).
            raise AIInvocationError(
                "ANTHROPIC_API_KEY is not set — required for the anthropic_api provider"
            )

    def _invoke(
        self, model: str, assembled: str, *, phase: str, max_tokens: int
    ) -> str:
        url = f"{self._base_url}/messages"
        headers = {
            "content-type": "application/json",
            "x-api-key": self._api_key,  # secret in the HEADER, never the URL
            "anthropic-version": self._version,
        }
        body = json.dumps(
            {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": assembled}],
            }
        ).encode("utf-8")
        try:
            status, response_text = self._transport(url, headers, body, self._timeout)
        except AITimeout:
            raise
        except OSError as exc:  # connect/socket failure → transient
            raise AITransientError(f"anthropic API unreachable: {exc}") from exc

        if status in (401, 403):
            # Bad/blocked key — retrying won't help; never echo the key or body.
            raise AIInvocationError(
                "anthropic API rejected the key (check ANTHROPIC_API_KEY)"
            )
        if status == 400:
            # A malformed request won't succeed on retry — surface it, don't loop.
            raise AIInvocationError("anthropic API rejected the request (HTTP 400)")
        if status == 429 or status == 529 or 500 <= status < 600:
            # Rate-limited / overloaded / server error — all bounded-retryable.
            raise AITransientError(f"anthropic API returned HTTP {status}")
        if status != 200:
            raise AITransientError(f"anthropic API returned HTTP {status}")

        text, usage = parse_anthropic_response(response_text, model=model)
        record_usage(usage, phase=phase)
        text = text.strip()
        if not text:
            raise AITransientError("anthropic API returned empty output")
        return text
