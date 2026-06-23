"""AI usage capture — parse the `claude -p --output-format json` envelope (ADR-0049).

The Claude CLI, invoked with ``--output-format json``, returns a single JSON
envelope on stdout carrying the model output (``result``) AND the ACTUAL billed
usage of the invocation: ``total_cost_usd`` (real dollars), the token breakdown
(``usage``), and a per-model rollup (``modelUsage``). This module turns that
envelope into a ``CliUsage`` record and buffers records per run via a context
variable, so the synchronous, run-agnostic provider can emit usage that the async
orchestration layer (which owns the run id + DB session) drains and persists.

Capture is STRICTLY best-effort: ``parse_envelope`` never raises — malformed,
non-JSON, or field-missing output falls back to treating stdout as the model text
and flags usage as unavailable, so usage capture can never break or alter
generation. ``total_cost_usd`` is the real billed cost of OUR CLI invocation,
which INCLUDES the Claude Code harness/system-prompt/tool-schema tokens and prompt
caching — it is the honest "what this call cost us to invoke", not a clean
prompt+completion figure, and it varies with cache warmth (ADR-0049). Cache-read
and cache-creation tokens are recorded separately so the breakdown stays legible.
"""

from __future__ import annotations

import json
from contextvars import ContextVar, Token
from dataclasses import dataclass, field

# The phase a usage record is attributed to. String-equal to the incident phase
# vocabulary (app.incidents.capture) where they overlap, but kept self-contained so
# the AI layer carries no import dependency on the incident module.
PHASE_GENERATION = "generation"
PHASE_TRIAGE = "triage"


@dataclass(frozen=True)
class CliUsage:
    """One CLI invocation's usage + actual billed cost (best-effort).

    ``available`` is False when the envelope could not be parsed or carried no
    usage block; the call still succeeded (the model text is returned) but the
    usage numbers are unknown and recorded as null/flagged. ``is_error`` surfaces
    the envelope's own ``is_error`` honestly rather than swallowing it.
    """

    available: bool
    is_error: bool = False
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    total_cost_usd: float | None = None
    model_cost_usd: float | None = None

    @classmethod
    def unavailable(
        cls, *, model: str | None = None, is_error: bool = False
    ) -> CliUsage:
        return cls(available=False, model=model, is_error=is_error)


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, int | float) else None


def _model_cost(model_usage: object, model: str | None) -> float | None:
    """Best-effort per-model cost from the ``modelUsage`` rollup for ``model``.

    The CLI keys ``modelUsage`` by the resolved model id (which may differ from the
    requested alias, e.g. a dated suffix), so we try the exact key, then any key
    that starts with the requested model, before giving up (None). The authoritative
    figure stays ``total_cost_usd``; this is the per-model attribution hint.
    """
    if not isinstance(model_usage, dict) or model is None:
        return None
    entry = model_usage.get(model)
    if not isinstance(entry, dict):
        for key, value in model_usage.items():
            if (
                isinstance(key, str)
                and isinstance(value, dict)
                and key.startswith(model)
            ):
                entry = value
                break
    if not isinstance(entry, dict):
        return None
    return _as_float(entry.get("costUSD"))


def parse_envelope(stdout: str, *, model: str | None = None) -> tuple[str, CliUsage]:
    """Parse a ``claude -p --output-format json`` envelope → (output_text, usage).

    NEVER raises. On valid JSON with a usage block, returns the ``result`` text and
    a populated ``CliUsage``. On non-JSON, a non-object, a missing ``result``, or a
    missing/!dict ``usage``, falls back to treating ``stdout`` as the output text and
    returns ``CliUsage.unavailable`` (flagged), so the call still succeeds.
    """
    try:
        envelope = json.loads(stdout)
    except (json.JSONDecodeError, ValueError, TypeError):
        return stdout, CliUsage.unavailable(model=model)
    if not isinstance(envelope, dict):
        return stdout, CliUsage.unavailable(model=model)

    result = envelope.get("result")
    text = result if isinstance(result, str) else stdout
    is_error = bool(envelope.get("is_error", False))

    usage = envelope.get("usage")
    if not isinstance(usage, dict):
        return text, CliUsage.unavailable(model=model, is_error=is_error)

    return text, CliUsage(
        available=True,
        is_error=is_error,
        model=model,
        input_tokens=_as_int(usage.get("input_tokens")),
        output_tokens=_as_int(usage.get("output_tokens")),
        cache_creation_input_tokens=_as_int(usage.get("cache_creation_input_tokens")),
        cache_read_input_tokens=_as_int(usage.get("cache_read_input_tokens")),
        total_cost_usd=_as_float(envelope.get("total_cost_usd")),
        model_cost_usd=_model_cost(envelope.get("modelUsage"), model),
    )


# --- per-run collection seam -------------------------------------------------
#
# Providers are synchronous and run-agnostic; the run id only exists later, in the
# async orchestration layer. A context variable bridges the two without threading a
# buffer through every render call: the orchestrator installs a collector for the
# duration of a run, provider calls append to it, and the orchestrator drains it
# once the run row exists. ContextVars are per-asyncio-task, so concurrent runs in
# one process never cross-attribute.


@dataclass
class UsageRecord:
    """A single captured usage entry plus the phase it occurred in."""

    phase: str
    usage: CliUsage


@dataclass
class UsageCollector:
    """An in-memory buffer of usage records for one run (drained by the caller)."""

    records: list[UsageRecord] = field(default_factory=list)

    def add(self, phase: str, usage: CliUsage) -> None:
        self.records.append(UsageRecord(phase=phase, usage=usage))


_collector: ContextVar[UsageCollector | None] = ContextVar(
    "ai_usage_collector", default=None
)


def install_collector(collector: UsageCollector) -> Token[UsageCollector | None]:
    """Make ``collector`` the active sink for the current context. Returns a token
    to pass to ``reset_collector`` (use try/finally)."""
    return _collector.set(collector)


def reset_collector(token: Token[UsageCollector | None]) -> None:
    _collector.reset(token)


def record_usage(usage: CliUsage, *, phase: str) -> None:
    """Append a usage record to the active collector, if any (best-effort no-op).

    Never raises and never blocks the caller: when no collector is installed (e.g. a
    provider call outside an instrumented run), the usage is simply dropped.
    """
    collector = _collector.get()
    if collector is not None:
        collector.add(phase, usage)
