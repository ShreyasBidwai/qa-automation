"""Gemini API provider — the second AIProvider backend (TRD §6).

Calls Google's Generative Language API (``models/{model}:generateContent``) over
HTTPS. Mirrors :class:`~app.ai.claude_cli.ClaudeCliProvider`: it enforces the same
token budget on the assembled context, applies a timeout, retries transient failures
with bounded backoff + jitter, and records usage — so the two providers are
interchangeable behind ``AIProvider`` and chosen per project.

Rate-limit-aware model fallback (generation path): Gemini returns HTTP 429
RESOURCE_EXHAUSTED for BOTH per-minute and per-day quota exhaustion, distinguished
ONLY by the response body — which we parse (never hardcode a quota number, we react
to the API's own QuotaFailure signal). A per-MINUTE 429 waits (honoring the API's
RetryInfo) and retries the SAME model, bounded; a per-DAY 429 marks that model
day-exhausted and advances to the NEXT model in the chain. When every model is
day-exhausted the generation fails with a clear terminal ``AllModelsExhausted`` —
it never hangs. Day-exhaustion is in-memory only (a next-UTC-midnight reset); DB
persistence is out of scope.

Security: the API key is a SECRET. It comes from the environment ONLY
(``GEMINI_API_KEY``), is sent via the ``x-goog-api-key`` HEADER (never the URL — a
key in a URL leaks into logs/proxies/history), and is never logged, returned, or
stored. No prompt, context, or output text is logged. The HTTP call is injected as a
``Transport`` so tests exercise budget/retry/timeout/parse/fallback without any
network — the DEFAULT transport (``_urllib_transport``) is the real one, so the
runtime path makes a real call once a key is supplied.
"""

from __future__ import annotations

import datetime as dt
import enum
import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from app.core.config import Settings

from .budget import BudgetStrategy, PromptParts, build_within_budget, estimate_tokens
from .errors import (
    AIInvocationError,
    AITimeout,
    AITransientError,
    AllModelsExhausted,
)
from .prompts import GENERATE_INSTRUCTION, TRIAGE_INSTRUCTION
from .retry import with_retries
from .triage import parse_triage_label, render_failure
from .types import FailureEvidence, Subgraph, TriageLabel
from .usage import PHASE_GENERATION, PHASE_TRIAGE, CliUsage, record_usage

# Triage prompts are tiny; a small budget keeps the call cheap (build_within_budget
# trims a giant trace). Triage uses the primary model with a bounded retry — no
# day-fallback chain (a transient quota failure surfaces retryable, then best-effort).
_TRIAGE_BUDGET_TOKENS = 8000

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


# --- 429 classification: per-minute vs per-day exhaustion --------------------


class QuotaScope(enum.Enum):
    """How a 429 RESOURCE_EXHAUSTED should be handled."""

    MINUTE = "minute"  # transient — wait (RetryInfo) + retry the SAME model
    DAY = "day"  # advance to the NEXT model; this one is done until midnight


# A protobuf Duration string, e.g. "15s" or "1.5s".
_RETRY_DELAY_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*s\s*$")


def _parse_retry_delay(details: list[object]) -> float | None:
    """Seconds from a ``google.rpc.RetryInfo`` detail's ``retryDelay``, if present."""
    for detail in details:
        if not isinstance(detail, dict):
            continue
        if str(detail.get("@type", "")).endswith("RetryInfo"):
            match = _RETRY_DELAY_RE.match(str(detail.get("retryDelay", "")))
            if match:
                return float(match.group(1))
    return None


def classify_quota_failure(body: str) -> tuple[QuotaScope, float | None]:
    """Classify a Gemini 429 body → ``(scope, retry_delay_seconds | None)``.

    Reads ``error.details[]`` for a ``google.rpc.QuotaFailure`` and inspects each
    violation's ``quotaId``/``quotaMetric`` (case-insensitive substring):
      * an unambiguous ``PerDay`` quota ⇒ ``DAY``
      * a ``PerMinute`` quota ⇒ ``MINUTE``
      * a 429 with NO parseable QuotaFailure, or an ambiguous one ⇒ ``MINUTE``

    The MINUTE default is deliberate and CONSERVATIVE: we never burn a model off the
    chain (day-exhaustion) on a signal we cannot confirm. ``retry_delay`` comes from a
    sibling ``RetryInfo`` detail when present. Pure; never raises.
    """
    try:
        envelope = json.loads(body)
    except (json.JSONDecodeError, ValueError, TypeError):
        return QuotaScope.MINUTE, None
    error = envelope.get("error") if isinstance(envelope, dict) else None
    details = error.get("details") if isinstance(error, dict) else None
    if not isinstance(details, list):
        return QuotaScope.MINUTE, None

    retry_delay = _parse_retry_delay(details)
    saw_day = False
    saw_minute = False
    for detail in details:
        if not isinstance(detail, dict):
            continue
        if not str(detail.get("@type", "")).endswith("QuotaFailure"):
            continue
        violations = detail.get("violations")
        if not isinstance(violations, list):
            continue
        for violation in violations:
            if not isinstance(violation, dict):
                continue
            text = f"{violation.get('quotaId', '')} {violation.get('quotaMetric', '')}"
            text = text.lower()
            has_day = "perday" in text
            has_minute = "perminute" in text
            # Only an UNAMBIGUOUS per-day signal advances the chain; a violation that
            # somehow names both is ambiguous → leave it to the conservative default.
            if has_day and not has_minute:
                saw_day = True
            elif has_minute:
                saw_minute = True

    if saw_day:
        return QuotaScope.DAY, retry_delay
    # saw_minute or nothing identifiable → MINUTE (conservative).
    _ = saw_minute
    return QuotaScope.MINUTE, retry_delay


def _bounded_minute_delay(retry_delay: float | None, cap: float) -> float:
    """The sleep for one per-minute wait: RetryInfo if given (capped), else the cap."""
    if retry_delay is None:
        return cap
    return min(retry_delay, cap)


# --- in-memory per-model day-quota exhaustion (next-UTC-midnight reset) -------


def _next_utc_midnight(now: float) -> float:
    """Epoch seconds of the next 00:00 UTC strictly after ``now`` (the reset point)."""
    moment = dt.datetime.fromtimestamp(now, tz=dt.UTC)
    reset = dt.datetime.combine(
        moment.date() + dt.timedelta(days=1), dt.time.min, tzinfo=dt.UTC
    )
    return reset.timestamp()


class DayExhaustionRegistry:
    """Tracks which models are per-day-quota-exhausted, with a midnight-UTC reset.

    In-memory ONLY (a process-shared default instance lets a model marked exhausted
    stay so across runs in the same worker); NOT persisted to the DB. A model resets
    automatically once the clock passes its next-UTC-midnight window.
    """

    def __init__(self) -> None:
        self._reset_at: dict[str, float] = {}

    def is_exhausted(self, model: str, now: float) -> bool:
        reset = self._reset_at.get(model)
        if reset is None:
            return False
        if now >= reset:
            del self._reset_at[model]  # window rolled over — clear it
            return False
        return True

    def mark(self, model: str, now: float) -> None:
        self._reset_at[model] = _next_utc_midnight(now)


# Process-shared default so day-exhaustion outlives a single generation/run. Tests
# inject a fresh registry to stay isolated.
_DEFAULT_DAY_REGISTRY = DayExhaustionRegistry()


def _resolve_model_chain(settings: Settings) -> list[str]:
    """The ordered fallback chain. ``GEMINI_MODEL_CHAIN`` if set, else the single
    ``gemini_generate_model`` (so the existing single-model path is unchanged)."""
    raw = settings.gemini_model_chain or ""
    chain = [model.strip() for model in raw.split(",") if model.strip()]
    return chain or [settings.gemini_generate_model]


# Internal control-flow signals for the chain loop. Deliberately NOT subclasses of
# AIProviderError so the shared ``with_retries`` (which retries only AITimeout /
# AITransientError) re-raises them straight through to the per-model handler.


class _DayExhausted(Exception):
    """A model returned a per-day 429 — advance the chain, do not retry it."""

    def __init__(self, model: str) -> None:
        self.model = model
        super().__init__(model)


class _MinuteRateLimited(Exception):
    """A model returned a per-minute 429 — wait + retry the SAME model (bounded)."""

    def __init__(self, *, model: str, retry_delay: float | None) -> None:
        self.model = model
        self.retry_delay = retry_delay
        super().__init__(model)


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
        clock: Callable[[], float] = time.time,
        day_registry: DayExhaustionRegistry | None = None,
    ) -> None:
        self._api_key = settings.gemini_api_key or ""
        self._model_chain = _resolve_model_chain(settings)
        self._base_url = settings.gemini_base_url.rstrip("/")
        self._timeout = settings.ai_timeout_seconds
        self._max_attempts = settings.ai_max_attempts
        self._base_delay = settings.ai_retry_base_delay_seconds
        self._max_delay = settings.ai_retry_max_delay_seconds
        self._max_minute_retries = max(1, settings.gemini_max_minute_retries)
        self._minute_cap = settings.gemini_minute_retry_cap_seconds
        self._strategy = BudgetStrategy(settings.ai_budget_strategy)
        # The DEFAULT is the REAL HTTP transport — the runtime path makes a real call
        # (a fake is injected ONLY by tests). Selecting gemini never falls back to a
        # stub: that is a separate provider mode in the factory.
        self._transport = transport or _urllib_transport
        self._sleep = sleep
        self._clock = clock
        self._day_registry = day_registry or _DEFAULT_DAY_REGISTRY

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
                "model_chain": self._model_chain,
                "estimated_tokens": estimate_tokens(assembled),
                "budget_tokens": budget_tokens,
            },
        )

        # Walk the fallback chain. A per-day 429 marks the model and advances; a
        # transient give-up (minute-quota not cleared, timeout, 5xx) is remembered so
        # a fully-transient failure surfaces as retryable rather than as the terminal
        # AllModelsExhausted (which is reserved for an all-day-exhausted chain).
        last_transient: AITransientError | None = None
        for model in self._model_chain:
            if self._day_registry.is_exhausted(model, self._clock()):
                logger.info("ai.generate.skip_day_exhausted", extra={"model": model})
                continue
            try:
                output = self._generate_with_model(model, assembled)
            except _DayExhausted:
                logger.warning("ai.generate.day_exhausted", extra={"model": model})
                self._day_registry.mark(model, self._clock())
                continue
            except AITransientError as exc:
                # Minute-quota give-up (or another transient) on this model — try the
                # next one, but keep the error in case the whole chain is transient.
                logger.warning(
                    "ai.generate.model_transient",
                    extra={"model": model, "error": type(exc).__name__},
                )
                last_transient = exc
                continue
            logger.info(
                "ai.generate.ok",
                extra={"model": model, "output_chars": len(output)},
            )
            return output

        if last_transient is not None:
            # At least one model failed transiently (not day-exhausted) — retryable.
            raise last_transient
        raise AllModelsExhausted(self._model_chain)

    def _generate_with_model(self, model: str, assembled: str) -> str:
        """One model: the existing bounded backoff (timeout/5xx/connection/empty)
        wrapped in a per-MINUTE-quota wait loop that honors RetryInfo and is bounded
        by ``gemini_max_minute_retries``. A per-DAY 429 propagates out (not handled
        here) so the caller can advance the chain."""
        minute_attempts = 0
        while True:
            minute_attempts += 1
            try:
                return with_retries(
                    lambda: self._invoke_model(model, assembled),
                    max_attempts=self._max_attempts,
                    base_delay=self._base_delay,
                    max_delay=self._max_delay,
                    retry_on=(AITimeout, AITransientError),
                    sleep=self._sleep,
                )
            except _MinuteRateLimited as exc:
                if minute_attempts >= self._max_minute_retries:
                    # Bounded — never an unbounded wait loop. Give up on THIS model;
                    # surface as transient so the chain can move on / a retry can.
                    raise AITransientError(
                        f"gemini per-minute quota for model {model} did not clear "
                        f"after {minute_attempts} attempts"
                    ) from exc
                self._sleep(_bounded_minute_delay(exc.retry_delay, self._minute_cap))

    def _invoke_model(
        self, model: str, assembled: str, *, phase: str = PHASE_GENERATION
    ) -> str:
        url = f"{self._base_url}/models/{model}:generateContent"
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
        if status == 429:
            # Per-minute vs per-day is in the BODY, not the status — classify it.
            scope, retry_delay = classify_quota_failure(response_text)
            if scope is QuotaScope.DAY:
                raise _DayExhausted(model)
            raise _MinuteRateLimited(model=model, retry_delay=retry_delay)
        if 500 <= status < 600:
            raise AITransientError(f"gemini API returned HTTP {status}")
        if status != 200:
            raise AITransientError(f"gemini API returned HTTP {status}")

        text, usage = parse_gemini_response(response_text, model=model)
        record_usage(usage, phase=phase)
        text = text.strip()
        if not text:
            raise AITransientError("gemini API returned empty output")
        return text

    def triage(self, failure: FailureEvidence) -> TriageLabel:
        """Classify a failing result via the primary model (ADR-0049 usage capture).

        Single model + bounded retry (no day-fallback chain): a 429 is converted to a
        retryable transient error, so triage stays simple and, on a hard failure,
        raises the same bounded AI errors as generate for the caller to treat
        best-effort.
        """
        if not self._api_key:
            raise AIInvocationError(
                "GEMINI_API_KEY is not set — required for the gemini provider"
            )
        parts = PromptParts(
            instruction=TRIAGE_INSTRUCTION,
            user_prompt=render_failure(failure),
            context_text="",
        )
        assembled = build_within_budget(
            parts, _TRIAGE_BUDGET_TOKENS, strategy=self._strategy
        )
        model = self._model_chain[0]
        output = with_retries(
            lambda: self._triage_invoke(model, assembled),
            max_attempts=self._max_attempts,
            base_delay=self._base_delay,
            max_delay=self._max_delay,
            retry_on=(AITimeout, AITransientError),
            sleep=self._sleep,
        )
        return parse_triage_label(output)

    def _triage_invoke(self, model: str, assembled: str) -> str:
        # Reuse the one HTTP path; a 429 (either quota scope) becomes a retryable
        # transient error — triage doesn't carry the generate path's day registry.
        try:
            return self._invoke_model(model, assembled, phase=PHASE_TRIAGE)
        except (_DayExhausted, _MinuteRateLimited) as exc:
            raise AITransientError("gemini triage was rate-limited") from exc
