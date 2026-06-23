"""Capture seams — phases, exception phase-tagging, and provider wrappers (ADR-0047).

The phase an incident is attributed to. The job worker is the universal seam (every
piece of Polaris's autonomous work runs as a durable job), so it derives the phase
from the job kind (ingest / execution) and records the failure. Inner seams that
want a more specific phase — provider calls — TAG the exception as it passes
through; the worker reads the tag and attributes the incident precisely, without
needing a database session at the inner seam (providers are synchronous).

Tagging is pure metadata on the exception object: it never swallows, never alters
control flow, and the underlying call re-raises exactly as before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.enums import JobKind

if TYPE_CHECKING:  # runtime import would cycle (ai/embeddings factories import this)
    from app.ai.types import AIProvider, FailureEvidence, Subgraph, TriageLabel
    from app.embeddings.types import EmbeddingProvider, Vector

# The phases an incident can be attributed to (validated strings; no pg enum).
PHASE_INGEST = "ingest"
PHASE_GENERATION = "generation"
PHASE_EXECUTION = "execution"
PHASE_ORCHESTRATOR = "orchestrator"
PHASE_JOB = "job"
PHASE_PROVIDER = "provider"
PHASES = frozenset(
    {
        PHASE_INGEST,
        PHASE_GENERATION,
        PHASE_EXECUTION,
        PHASE_ORCHESTRATOR,
        PHASE_JOB,
        PHASE_PROVIDER,
    }
)

_PHASE_ATTR = "_polaris_incident_phase"
_PHASE_FOR_KIND: dict[JobKind, str] = {
    JobKind.RUN: PHASE_EXECUTION,
    JobKind.INGEST: PHASE_INGEST,
}


def tag_phase(exc: BaseException, phase: str) -> None:
    """Tag ``exc`` with the phase it occurred in, if not already tagged.

    Used by inner seams so the outer recorder attributes precisely. Pure metadata —
    some built-in exceptions forbid attribute assignment, which is harmless here.
    """
    if not hasattr(exc, _PHASE_ATTR):
        try:
            setattr(exc, _PHASE_ATTR, phase)
        except Exception:  # noqa: BLE001 — best-effort tagging only
            pass


def phase_of(exc: BaseException, *, default: str) -> str:
    """The tagged phase if present, else ``default`` (e.g. derived from job kind)."""
    tagged = getattr(exc, _PHASE_ATTR, None)
    return tagged if isinstance(tagged, str) else default


def phase_for_job_kind(kind: JobKind) -> str:
    return _PHASE_FOR_KIND.get(kind, PHASE_JOB)


class _PhaseTaggingAIProvider:
    """Wraps an AIProvider, tagging any failure as the ``provider`` phase.

    Synchronous (the provider is); tags + re-raises — never swallows, never alters
    the successful result.
    """

    def __init__(self, inner: AIProvider) -> None:
        self._inner = inner

    def generate(self, prompt: str, context: Subgraph, budget_tokens: int) -> str:
        try:
            return self._inner.generate(prompt, context, budget_tokens)
        except Exception as exc:
            tag_phase(exc, PHASE_PROVIDER)
            raise

    def triage(self, failure: FailureEvidence) -> TriageLabel:
        try:
            return self._inner.triage(failure)
        except Exception as exc:
            tag_phase(exc, PHASE_PROVIDER)
            raise


class _PhaseTaggingEmbeddingProvider:
    """Wraps an EmbeddingProvider, tagging any ``embed`` failure as ``provider``."""

    def __init__(self, inner: EmbeddingProvider) -> None:
        self._inner = inner
        self.dimension = inner.dimension

    def embed(self, texts: list[str]) -> list[Vector]:
        try:
            return self._inner.embed(texts)
        except Exception as exc:
            tag_phase(exc, PHASE_PROVIDER)
            raise


def capturing_ai_provider(inner: AIProvider) -> AIProvider:
    """Wrap an AI provider so its failures are tagged as the ``provider`` phase."""
    return _PhaseTaggingAIProvider(inner)


def capturing_embedding_provider(inner: EmbeddingProvider) -> EmbeddingProvider:
    """Wrap an embedding provider so its failures are tagged as ``provider``."""
    return _PhaseTaggingEmbeddingProvider(inner)
