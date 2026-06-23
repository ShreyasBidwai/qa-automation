"""RunProgressEmitter — best-effort, side-effect-safe run-progress emission (ADR-0050).

Mirrors :class:`~app.incidents.recorder.IncidentRecorder`: each event is written in a
FRESH session that commits independently, so (a) a live streaming reader on another
connection sees events as the run produces them, and (b) the progress history
survives even when the run's own transaction rolls back. It NEVER raises — a failed
emit is logged, not fatal — so emitting progress can neither break nor stall a run
(the same rule as incident capture).

Ordering is deterministic: ``seq`` is a monotonic in-memory counter assigned BEFORE
the write, so events are ordered by ``seq`` regardless of commit timing; the unique
``(run_id, seq)`` index is the backstop. ``run_id`` is the durable run handle the API
exposes — the RUN job id (every ``/runs/{run_id}`` route already resolves that id).

The emitter is installed for the duration of a run via a context variable, so the
synchronous-looking orchestrator/lifecycle seams emit through ``emit(...)`` without
threading an emitter object through every call; a seam with no emitter installed (any
non-run path) is a silent no-op.
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar, Token
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.run_event import RunEvent

logger = logging.getLogger("app.progress")

# --- the journey vocabulary --------------------------------------------------
# Phases a run moves through (validated strings; no pg enum). PHASE_RUN frames the
# run as a whole (its terminal event ends the live stream).
PHASE_RUN = "run"
PHASE_SELECT = "select"
PHASE_GENERATE = "generate"
PHASE_EXECUTE = "execute"
PHASE_REVIEW = "review"
PHASES = frozenset(
    {PHASE_RUN, PHASE_SELECT, PHASE_GENERATE, PHASE_EXECUTE, PHASE_REVIEW}
)

# A step's status. ``started`` opens a step; the rest close it.
STATUS_STARTED = "started"
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUSES = frozenset({STATUS_STARTED, STATUS_PASSED, STATUS_FAILED, STATUS_SKIPPED})

# The run-level completion statuses that end a live stream.
_TERMINAL_STATUSES = frozenset({STATUS_PASSED, STATUS_FAILED, STATUS_SKIPPED})

_STEP_LIMIT = 500  # matches the run_events.step column width


def is_terminal(phase: str, status: str) -> bool:
    """True for the run-level completion event that closes the live stream."""
    return phase == PHASE_RUN and status in _TERMINAL_STATUSES


class RunProgressEmitter:
    """Emits ordered run-progress events, each committed in its own session."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        run_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> None:
        self._sm = sessionmaker
        self._run_id = run_id
        self._project_id = project_id
        self._seq = 0

    async def emit(
        self,
        *,
        phase: str,
        step: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Persist one progress event. Best-effort: any failure is logged, never
        raised, so progress emission can't break or stall the run."""
        seq = self._seq
        self._seq += 1
        try:
            event = RunEvent(
                run_id=self._run_id,
                project_id=self._project_id,
                seq=seq,
                phase=phase,
                step=step[:_STEP_LIMIT],
                status=status,
                detail=detail,
            )
            async with self._sm() as session:
                session.add(event)
                await session.commit()
        except Exception:  # noqa: BLE001 — emission is best-effort, never fatal
            logger.exception(
                "progress.emit_failed",
                extra={"run_id": str(self._run_id), "phase": phase, "seq": seq},
            )


# --- the per-run install seam (context variable) -----------------------------

_current: ContextVar[RunProgressEmitter | None] = ContextVar(
    "run_progress_emitter", default=None
)


def install_emitter(emitter: RunProgressEmitter) -> Token[RunProgressEmitter | None]:
    """Make ``emitter`` the active sink for the current context. Returns a token to
    pass to :func:`reset_emitter` (use try/finally)."""
    return _current.set(emitter)


def reset_emitter(token: Token[RunProgressEmitter | None]) -> None:
    _current.reset(token)


async def emit(
    *,
    phase: str,
    step: str,
    status: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """Emit a progress event to the installed emitter, if any (best-effort no-op).

    Never raises: with no emitter installed (any non-run path) it does nothing, and a
    failure inside the emitter is swallowed there.
    """
    emitter = _current.get()
    if emitter is not None:
        await emitter.emit(phase=phase, step=step, status=status, detail=detail)
