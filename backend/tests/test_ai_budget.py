"""Hard token-budget enforcement (TRD §6): truncate or raise, never overshoot."""

from __future__ import annotations

import pytest

from app.ai.budget import (
    BudgetStrategy,
    PromptParts,
    build_within_budget,
    estimate_tokens,
)
from app.ai.errors import BudgetExceeded


def _parts(context: str) -> PromptParts:
    return PromptParts(instruction="INSTR", user_prompt="do x", context_text=context)


def test_under_budget_returns_full_prompt_unchanged() -> None:
    out = build_within_budget(
        _parts("small context"), budget_tokens=10_000, strategy=BudgetStrategy.TRUNCATE
    )
    assert "small context" in out
    assert "truncated" not in out
    assert estimate_tokens(out) <= 10_000


def test_over_budget_truncate_fits_within_budget_and_marks() -> None:
    budget = 200
    out = build_within_budget(
        _parts("x" * 100_000), budget_tokens=budget, strategy=BudgetStrategy.TRUNCATE
    )
    assert estimate_tokens(out) <= budget  # the invariant: never over budget
    assert "truncated to fit token budget" in out
    assert "do x" in out  # the user prompt is preserved


def test_over_budget_raise_raises_typed_error() -> None:
    with pytest.raises(BudgetExceeded) as excinfo:
        build_within_budget(
            _parts("y" * 100_000), budget_tokens=200, strategy=BudgetStrategy.RAISE
        )
    assert excinfo.value.budget == 200
    assert excinfo.value.estimated > 200


def test_budget_too_small_for_instruction_raises_even_when_truncating() -> None:
    parts = PromptParts(
        instruction="I" * 4000, user_prompt="p" * 4000, context_text="ctx"
    )
    with pytest.raises(BudgetExceeded):
        build_within_budget(parts, budget_tokens=10, strategy=BudgetStrategy.TRUNCATE)
