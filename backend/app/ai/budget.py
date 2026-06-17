"""Hard token-budget enforcement on assembled context (TRD §6, Arch §8).

A generation prompt is assembled deterministically from a fixed instruction, the
user prompt, and the rendered Subgraph context. The total must never exceed the
caller's `budget_tokens`: either the context is truncated deterministically to
fit, or a typed `BudgetExceeded` is raised. We never silently send an oversized
prompt.

Token counts are *estimates* (no tokenizer dependency): ~4 characters/token,
which is a deliberate over-approximation so the real prompt stays under budget.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, replace

from .errors import BudgetExceeded

CHARS_PER_TOKEN = 4
_TRUNCATION_MARKER = "\n…[context truncated to fit token budget]"


class BudgetStrategy(str, enum.Enum):
    TRUNCATE = "truncate"
    RAISE = "raise"


@dataclass(frozen=True)
class PromptParts:
    instruction: str
    user_prompt: str
    context_text: str


def estimate_tokens(text: str) -> int:
    """Deterministic token estimate (ceil of len/4)."""
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def render_prompt(parts: PromptParts) -> str:
    return (
        f"{parts.instruction}\n\n"
        f"## Task\n{parts.user_prompt}\n\n"
        f"## Context\n{parts.context_text}"
    )


def build_within_budget(
    parts: PromptParts, budget_tokens: int, *, strategy: BudgetStrategy
) -> str:
    """Assemble a prompt guaranteed to fit within ``budget_tokens``.

    Raises ``BudgetExceeded`` when over budget under RAISE, or when even the
    instruction + user prompt alone cannot fit (truncation can't help).
    """
    full = render_prompt(parts)
    if estimate_tokens(full) <= budget_tokens:
        return full

    if strategy is BudgetStrategy.RAISE:
        raise BudgetExceeded(estimated=estimate_tokens(full), budget=budget_tokens)

    # TRUNCATE: the instruction + user prompt are load-bearing and never cut.
    # If they don't fit even with an empty context, we cannot satisfy the budget.
    minimal = render_prompt(replace(parts, context_text=_TRUNCATION_MARKER.strip()))
    if estimate_tokens(minimal) > budget_tokens:
        raise BudgetExceeded(estimated=estimate_tokens(minimal), budget=budget_tokens)

    # Shrink the context deterministically (~12.5% per step) until it fits.
    context = parts.context_text
    while context:
        candidate = render_prompt(
            replace(parts, context_text=context + _TRUNCATION_MARKER)
        )
        if estimate_tokens(candidate) <= budget_tokens:
            return candidate
        context = context[: len(context) - max(1, len(context) // 8)]

    return minimal
