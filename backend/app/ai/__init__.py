"""Pluggable AI layer (TRD §5–6).

A single provider-agnostic interface (`AIProvider`) with a `claude -p` dev
implementation and a deterministic stub for tests. Production can swap to an
API/self-hosted provider without touching callers.
"""

from __future__ import annotations

from .errors import (
    AIInvocationError,
    AIProviderError,
    AITimeout,
    AITransientError,
    BudgetExceeded,
)
from .factory import build_ai_provider
from .types import AIProvider, FailureEvidence, Subgraph, SubgraphEdge, SubgraphNode

__all__ = [
    "AIProvider",
    "Subgraph",
    "SubgraphNode",
    "SubgraphEdge",
    "FailureEvidence",
    "build_ai_provider",
    "AIProviderError",
    "BudgetExceeded",
    "AITimeout",
    "AITransientError",
    "AIInvocationError",
]
