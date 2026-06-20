"""Test-authoring + autonomous modes (Architecture §4/§6).

Mode C — natural-language authoring: free text → intent → a proposed cross-layer
journey → generated, oracle-honest E2E PROPOSALS persisted via the never-clobber
lifecycle.

Mode B — autonomous orchestration (T8.2): select what to test from the Brain
(FullSweep | ChangeImpact), ensure cases exist, execute, and produce ranked
findings — bounded, deterministic, no human in the loop. Reuses the generators,
runners, and reporting pipeline; only sequences them.
"""

from __future__ import annotations

from .errors import ModeBError
from .mode_b import (
    BrainResolver,
    EnsuredCase,
    ModeBBounds,
    ModeBOrchestrator,
    ModeBRunReport,
    TargetGenerator,
)
from .mode_c import ModeCOrchestrator, ModeCResult, build_mode_c_orchestrator
from .proposals import generate_proposed_cases
from .selection import (
    ChangeImpactStrategy,
    FullSweepStrategy,
    Selection,
    SelectionStrategy,
    SelectionStrategyKind,
    Target,
    build_selection_strategy,
)

__all__ = [
    "BrainResolver",
    "ChangeImpactStrategy",
    "EnsuredCase",
    "FullSweepStrategy",
    "ModeBBounds",
    "ModeBError",
    "ModeBOrchestrator",
    "ModeBRunReport",
    "ModeCOrchestrator",
    "ModeCResult",
    "Selection",
    "SelectionStrategy",
    "SelectionStrategyKind",
    "Target",
    "TargetGenerator",
    "build_mode_c_orchestrator",
    "build_selection_strategy",
    "generate_proposed_cases",
]
