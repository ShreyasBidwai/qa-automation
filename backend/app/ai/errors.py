"""Typed AI-layer errors (Standards §7 — explicit, no bare except, no swallow).

Taxonomy:
- BudgetExceeded: context over the hard budget; raised pre-call (not retryable).
- AITimeout: the provider call timed out (transient / retryable).
- AITransientError: recoverable failure, e.g. non-zero exit (retryable).
- AIInvocationError: permanent failure, e.g. CLI missing (not retryable).
"""

from __future__ import annotations


class AIProviderError(Exception):
    """Base class for all AI-layer errors."""


class BudgetExceeded(AIProviderError):
    def __init__(self, *, estimated: int, budget: int) -> None:
        self.estimated = estimated
        self.budget = budget
        super().__init__(
            f"assembled context ~{estimated} tokens exceeds budget of {budget}"
        )


class AITimeout(AIProviderError):
    """The provider call exceeded its timeout. Transient — safe to retry."""


class AITransientError(AIProviderError):
    """A recoverable provider failure. Transient — safe to retry."""


class AIInvocationError(AIProviderError):
    """A permanent provider/configuration failure. Not retryable."""
