"""Structured run-progress events — plumbing for a live "watch the run" view (ADR-0050).

Emits ordered events ({run_id, seq, phase, step, status, detail}) at the real run
lifecycle seams (select → generate → execute step-by-step → review) so the frontend
can render the run as it happens. Emission is best-effort and side-effect-safe: a
failed emit is logged, not fatal, and never breaks or stalls a run (the same rule as
incident capture). Events are persisted (``run_events``) and consumed live over SSE
or replayed via a plain GET.
"""

from __future__ import annotations

from .emitter import (
    PHASE_EXECUTE,
    PHASE_GENERATE,
    PHASE_REVIEW,
    PHASE_RUN,
    PHASE_SELECT,
    PHASES,
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_SKIPPED,
    STATUS_STARTED,
    STATUSES,
    RunProgressEmitter,
    current_run_id,
    emit,
    install_emitter,
    is_terminal,
    reset_emitter,
)

__all__ = [
    "RunProgressEmitter",
    "current_run_id",
    "emit",
    "install_emitter",
    "reset_emitter",
    "is_terminal",
    "PHASES",
    "PHASE_RUN",
    "PHASE_SELECT",
    "PHASE_GENERATE",
    "PHASE_EXECUTE",
    "PHASE_REVIEW",
    "STATUSES",
    "STATUS_STARTED",
    "STATUS_PASSED",
    "STATUS_FAILED",
    "STATUS_SKIPPED",
]
