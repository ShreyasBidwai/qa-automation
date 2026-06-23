"""IncidentRecorder — best-effort, side-effect-safe capture (ADR-0047).

Writes an incident in a FRESH session (independent of the failed one, which is
typically aborting), so the record survives even when the work's own transaction
rolls back. It NEVER raises and NEVER swallows the underlying exception — the caller
records, then re-raises / handles exactly as it did before. A recording failure is
logged, not fatal (recording must never break a run).
"""

from __future__ import annotations

import logging
import traceback as _tb
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.incident import Incident

from .fingerprint import fingerprint_for

logger = logging.getLogger("app.incidents")

_MESSAGE_LIMIT = 4000  # cap a pathological exception message


class IncidentRecorder:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def record(
        self,
        exc: BaseException,
        *,
        phase: str,
        project_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        component: str | None = None,
    ) -> None:
        """Capture ``exc`` as an incident. Best-effort: any failure here is logged,
        never propagated — so capture can't break the underlying flow."""
        try:
            exc_type = type(exc).__name__
            traceback_text = "".join(
                _tb.format_exception(type(exc), exc, exc.__traceback__)
            )
            incident = Incident(
                phase=phase,
                component=component,
                project_id=project_id,
                run_id=run_id,
                exception_type=exc_type[:256],
                message=(str(exc) or exc_type)[:_MESSAGE_LIMIT],
                traceback=traceback_text,
                fingerprint=fingerprint_for(exc),
            )
            async with self._sm() as session:
                session.add(incident)
                await session.commit()
        except Exception:  # noqa: BLE001 — recording is best-effort, never fatal
            logger.exception("incidents.record_failed", extra={"phase": phase})
