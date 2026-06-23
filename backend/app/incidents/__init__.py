"""Structured capture of Polaris's own internal failures (dev-suite slice 1).

Records an :class:`~app.models.incident.Incident` at the real failure seams (the job
worker, and — tagged inward — provider calls) so an operator can diagnose a failed
run WITHOUT decoding raw logs. Capture is side-effect-safe: it never swallows or
alters the underlying exception, and a recording failure is logged, not fatal.

Scope (the honesty guardrail, ADR-0047): this CAPTURES and SURFACES failures for
humans. It does NOT aggregate, alert, or modify Polaris — and Polaris never
auto-modifies itself in response.
"""

from __future__ import annotations

from .capture import (
    PHASE_EXECUTION,
    PHASE_GENERATION,
    PHASE_INGEST,
    PHASE_JOB,
    PHASE_ORCHESTRATOR,
    PHASE_PROVIDER,
    PHASES,
    capturing_ai_provider,
    capturing_embedding_provider,
    phase_for_job_kind,
    phase_of,
    tag_phase,
)
from .fingerprint import fingerprint, fingerprint_for, location_of
from .recorder import IncidentRecorder

__all__ = [
    "IncidentRecorder",
    "fingerprint",
    "fingerprint_for",
    "location_of",
    "tag_phase",
    "phase_of",
    "phase_for_job_kind",
    "capturing_ai_provider",
    "capturing_embedding_provider",
    "PHASES",
    "PHASE_INGEST",
    "PHASE_GENERATION",
    "PHASE_EXECUTION",
    "PHASE_ORCHESTRATOR",
    "PHASE_JOB",
    "PHASE_PROVIDER",
]
