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
from .retry import with_retries
from .types import FailureEvidence, Subgraph, TriageLabel

logger = logging.getLogger("app.ai")

_GENERATE_INSTRUCTION = (
    "You are a test-generation engine for the QA Automation Platform. "
    "Using only the grounded context below, produce the requested test artifact. "
    "Do not invent endpoints, fields, or behavior absent from the context."
)


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
        argv = [self._cli_path, "-p", "--model", self._model]
        result = self._runner(argv, assembled, self._timeout)
        if result.returncode != 0:
            # stderr may echo prompt content — log the code only, not the body.
            logger.warning(
                "ai.generate.nonzero_exit",
                extra={"model": self._model, "returncode": result.returncode},
            )
            raise AITransientError(f"claude CLI exited with code {result.returncode}")
        output = result.stdout.strip()
        if not output:
            raise AITransientError("claude CLI returned empty output")
        return output

    def triage(self, failure: FailureEvidence) -> TriageLabel:
        raise NotImplementedError("triage lands in Sprint 7")
