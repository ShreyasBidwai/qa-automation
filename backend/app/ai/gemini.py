"""Gemini API provider — the second AIProvider backend (TRD §6).

Calls Google's Generative Language API (``models/{model}:generateContent``) over
HTTPS. Mirrors :class:`~app.ai.claude_cli.ClaudeCliProvider`: it enforces the same
token budget on the assembled context, applies a timeout, retries transient failures
with bounded backoff + jitter, and records usage — so the two providers are
interchangeable behind ``AIProvider`` and chosen per project.

Security: the API key is a SECRET. It comes from the environment ONLY
(``GEMINI_API_KEY``), is sent via the ``x-goog-api-key`` HEADER (never the URL — a
key in a URL leaks into logs/proxies/history), and is never logged, returned, or
stored. No prompt, context, or output text is logged. The HTTP call is injected as a
``Transport`` so tests exercise budget/retry/timeout/parse without any network.
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
from .prompts import GENERATE_INSTRUCTION
from .retry import with_retries
from .types import FailureEvidence, Subgraph, TriageLabel
from .usage import PHASE_GENERATION, CliUsage, record_usage

logger = logging.getLogger("app.ai")

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
        # An HTTP error response still carries a status + a body we want to classify.
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except TimeoutError as exc:
        raise AITimeout(f"gemini API timed out after {timeout}s") from exc


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_gemini_response(body: str, *, model: str | None) -> tuple[str, CliUsage]:
    """Parse a ``generateContent`` response → (output_text, usage). NEVER raises.

    Concatenates the first candidate's text parts; reads ``usageMetadata`` for the
    token counts (Gemini does not return a dollar cost, so ``total_cost_usd`` stays
    null). Malformed/blocked output falls back to empty text + unavailable usage,
    which the caller treats as a transient empty result.
    """
    try:
        envelope = json.loads(body)
    except (json.JSONDecodeError, ValueError, TypeError):
        return "", CliUsage.unavailable(model=model)
    if not isinstance(envelope, dict):
        return "", CliUsage.unavailable(model=model)

    text = ""
    candidates = envelope.get("candidates")
    if isinstance(candidates, list) and candidates:
        first = candidates[0]
        content = first.get("content") if isinstance(first, dict) else None
        parts = content.get("parts") if isinstance(content, dict) else None
        if isinstance(parts, list):
            text = "".join(
                part["text"]
                for part in parts
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )

    meta = envelope.get("usageMetadata")
    if not isinstance(meta, dict):
        return text, CliUsage.unavailable(model=model)
    return text, CliUsage(
        available=True,
        model=model,
        input_tokens=_as_int(meta.get("promptTokenCount")),
        output_tokens=_as_int(meta.get("candidatesTokenCount")),
        # Gemini's API response carries no billed dollar figure (unlike the Claude
        # CLI envelope), so cost is unknown, not zero.
        total_cost_usd=None,
    )


class GeminiProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = settings.gemini_api_key or ""
        self._model = settings.gemini_generate_model
        self._base_url = settings.gemini_base_url.rstrip("/")
        self._timeout = settings.ai_timeout_seconds
        self._max_attempts = settings.ai_max_attempts
        self._base_delay = settings.ai_retry_base_delay_seconds
        self._max_delay = settings.ai_retry_max_delay_seconds
        self._strategy = BudgetStrategy(settings.ai_budget_strategy)
        self._transport = transport or _urllib_transport
        self._sleep = sleep

    def generate(self, prompt: str, context: Subgraph, budget_tokens: int) -> str:
        if not self._api_key:
            # A config error, not transient — fail fast and clearly (don't retry).
            raise AIInvocationError(
                "GEMINI_API_KEY is not set — required for the gemini provider"
            )
        parts = PromptParts(
            instruction=GENERATE_INSTRUCTION,
            user_prompt=prompt,
            context_text=context.render(),
        )
        assembled = build_within_budget(parts, budget_tokens, strategy=self._strategy)
        logger.info(
            "ai.generate.start",
            extra={
                "model": self._model,
                "estimated_tokens": estimate_tokens(assembled),
                "budget_tokens": budget_tokens,
            },
        )
        output = with_retries(
            lambda: self._invoke(assembled),
            max_attempts=self._max_attempts,
            base_delay=self._base_delay,
            max_delay=self._max_delay,
            retry_on=(AITimeout, AITransientError),
            sleep=self._sleep,
        )
        logger.info(
            "ai.generate.ok",
            extra={"model": self._model, "output_chars": len(output)},
        )
        return output

    def _invoke(self, assembled: str) -> str:
        url = f"{self._base_url}/models/{self._model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,  # secret in the HEADER, never the URL
        }
        body = json.dumps({"contents": [{"parts": [{"text": assembled}]}]}).encode(
            "utf-8"
        )
        try:
            status, response_text = self._transport(url, headers, body, self._timeout)
        except AITimeout:
            raise
        except OSError as exc:  # connect/socket failure → transient
            raise AITransientError(f"gemini API unreachable: {exc}") from exc

        if status in (401, 403):
            # Bad/blocked key — retrying won't help; never echo the key or body.
            raise AIInvocationError(
                "gemini API rejected the key (check GEMINI_API_KEY)"
            )
        if status == 429 or 500 <= status < 600:
            raise AITransientError(f"gemini API returned HTTP {status}")
        if status != 200:
            raise AITransientError(f"gemini API returned HTTP {status}")

        text, usage = parse_gemini_response(response_text, model=self._model)
        record_usage(usage, phase=PHASE_GENERATION)
        text = text.strip()
        if not text:
            raise AITransientError("gemini API returned empty output")
        return text

    def triage(self, failure: FailureEvidence) -> TriageLabel:
        raise NotImplementedError("triage lands in Sprint 7")
