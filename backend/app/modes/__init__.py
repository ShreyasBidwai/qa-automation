"""Test-authoring modes (Architecture §4/§6).

Mode C — natural-language authoring: free text → intent → a proposed cross-layer
journey → generated, oracle-honest E2E PROPOSALS persisted via the never-clobber
lifecycle. The orchestrator + its factory are the integration entry points.
"""

from __future__ import annotations

from .mode_c import ModeCOrchestrator, ModeCResult, build_mode_c_orchestrator
from .proposals import generate_proposed_cases

__all__ = [
    "ModeCOrchestrator",
    "ModeCResult",
    "build_mode_c_orchestrator",
    "generate_proposed_cases",
]
