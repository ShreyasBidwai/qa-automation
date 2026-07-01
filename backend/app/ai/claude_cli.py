"""`claude -p` provider — the dev AIProvider implementation (TRD §6).

Shells out to the Claude CLI non-interactively. Enforces a hard token budget on
the assembled context before invoking, applies a timeout, and retries transient
failures with bounded exponential backoff + jitter. The prompt is passed on
stdin (never as an argv element, which would leak it to `ps`); no prompt,
context, or output text is ever logged (Standards §8).

The subprocess call is injected as a `CommandRunner` so tests exercise the
budget/retry/timeout logic without ever invoking the real CLI.
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.core.config import Settings

from .budget import (
    BudgetStrategy,
    PromptParts,
    build_within_budget,
    estimate_tokens,
)
from .errors import AIInvocationError, AITimeout, AITransientError
from .prompts import GENERATE_INSTRUCTION, TRIAGE_INSTRUCTION
from .retry import with_retries
from .triage import parse_triage_label, render_failure
from .types import FailureEvidence, Subgraph, TriageLabel
from .usage import PHASE_GENERATION, PHASE_TRIAGE, parse_envelope, record_usage

logger = logging.getLogger("app.ai")

_GENERATE_INSTRUCTION = GENERATE_INSTRUCTION
# Triage prompts are tiny (an instruction + one failure message); a small budget
# keeps the cheap-model call cheap while build_within_budget trims a giant trace.
_TRIAGE_BUDGET_TOKENS = 8000


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


# (argv, stdin_text, timeout_seconds) -> CommandResult.
# Implementations raise AITimeout / AITransientError / AIInvocationError.
CommandRunner = Callable[[Sequence[str], str, float], CommandResult]


def _subprocess_runner(
    argv: Sequence[str], stdin_text: str, timeout: float
) -> CommandResult:
    try:
        completed = subprocess.run(
            list(argv),
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AITimeout(f"claude CLI timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise AIInvocationError("claude CLI not found on PATH") from exc
    except OSError as exc:
        # Spawn-level failures are usually transient (e.g. resource limits).
        raise AITransientError(
            f"failed to invoke claude CLI: {type(exc).__name__}"
        ) from exc
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


class ClaudeCliProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        runner: CommandRunner | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._model = settings.ai_generate_model
        self._triage_model = settings.ai_triage_model
        self._cli_path = settings.claude_cli_path
        self._timeout = settings.ai_timeout_seconds
        self._max_attempts = settings.ai_max_attempts
        self._base_delay = settings.ai_retry_base_delay_seconds
        self._max_delay = settings.ai_retry_max_delay_seconds
        self._strategy = BudgetStrategy(settings.ai_budget_strategy)
        self._runner = runner or _subprocess_runner
        self._sleep = sleep

    def generate(self, prompt: str, context: Subgraph, budget_tokens: int) -> str:
        parts = PromptParts(
            instruction=_GENERATE_INSTRUCTION,
            user_prompt=prompt,
            context_text=context.render(),
        )
        # Raises BudgetExceeded rather than ever sending an oversized prompt.
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
            lambda: self._invoke(assembled, model=self._model, phase=PHASE_GENERATION),
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

    def _invoke(self, assembled: str, *, model: str, phase: str) -> str:
        # ``--output-format json`` returns a single envelope carrying the model text
        # (``result``) plus the actual billed usage; parsing is internal — callers
        # still receive only the output text (ADR-0049). ``model``/``phase`` let
        # generate (frontier) and triage (cheap tier) share this one invocation path.
        argv = [self._cli_path, "-p", "--output-format", "json", "--model", model]
        result = self._runner(argv, assembled, self._timeout)
        if result.returncode != 0:
            # stderr may echo prompt content — log the code only, not the body.
            logger.warning(
                "ai.invoke.nonzero_exit",
                extra={"model": model, "phase": phase, "returncode": result.returncode},
            )
            raise AITransientError(f"claude CLI exited with code {result.returncode}")
        # Best-effort capture: malformed/non-JSON output falls back to the raw stdout
        # as the text and flags usage unavailable — never breaks or alters the call.
        output, usage = parse_envelope(result.stdout, model=model)
        record_usage(usage, phase=phase)
        output = output.strip()
        if not output:
            raise AITransientError("claude CLI returned empty output")
        return output

    def triage(self, failure: FailureEvidence) -> TriageLabel:
        """Classify a failing result via the cheap-tier model (ADR-0049 usage capture).

        Runs the shared triage prompt through the ``ai_triage_model`` and parses the
        reply to a label. Raises the same bounded AI errors as generate on a hard
        failure; the caller (the run's triage phase) treats that best-effort.
        """
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
                assembled, model=self._triage_model, phase=PHASE_TRIAGE
            ),
            max_attempts=self._max_attempts,
            base_delay=self._base_delay,
            max_delay=self._max_delay,
            retry_on=(AITimeout, AITransientError),
            sleep=self._sleep,
        )
        return parse_triage_label(output)
