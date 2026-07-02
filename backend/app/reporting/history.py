"""Cross-run history classification (T7.4).

Fills the Finding ``status`` placeholder by classifying each finding against the
project's recent run history, joined on ``root_cause_key`` (ADR-0023): new vs
known vs regression vs flaky.

Over a bounded window of the N runs immediately prior to the current run (sourced
from the ``runs`` table, ordered deterministically), a finding's key is either
present or absent in each — a boolean presence vector. ``classify_history`` turns
that vector into a status (precedence flaky > regression > known > new); the
``HistoryClassifier`` builds the vector from the store and persists the status.
Deterministic and project-scoped; no new table (Standards §5, §7).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import FindingStatus
from app.models.finding import Finding
from app.repositories.finding_repository import FindingRepository
from app.repositories.run_repository import RunRepository

logger = logging.getLogger("app.reporting")

# How many prior runs form the history window (ADR-0023) — configurable per call.
DEFAULT_HISTORY_WINDOW = 10

# A key that flips present/absent at least this many times across the window is
# flaky (a single clear-and-return is one flip → regression, not flaky).
FLAKY_FLIP_THRESHOLD = 2


def classify_history(presence: Sequence[bool]) -> FindingStatus:
    """Classify a key from its presence vector over prior runs (oldest → newest).

    ``presence[i]`` is whether the key had a finding in window run ``i``. The
    current run is excluded (the finding is present now by definition).

    REGRESSION takes precedence over FLAKY (architecture-review DO-FIRST #3): a
    failure that was cleared (the immediately-prior run PASSED) and has now returned
    is a real, currently-reproducing break — surface it, never bury it as "flaky"
    just because older history flapped. FLAKY is reserved for a failure that is
    ONGOING at the prior→current boundary (prior run also failed) yet genuinely
    oscillates — noisy, but not a fresh regression. Precedence: regression > flaky >
    known > new.
    """
    seen = any(presence)
    last = presence[-1] if presence else False  # the immediately-prior run
    if seen and not last:
        return FindingStatus.REGRESSION  # cleared, then back — a live regression
    flips = sum(1 for a, b in zip(presence, presence[1:], strict=False) if a != b)
    if flips >= FLAKY_FLIP_THRESHOLD:
        return FindingStatus.FLAKY  # ongoing (prior failed) AND oscillating
    if last:
        return FindingStatus.KNOWN  # ongoing, stable
    return FindingStatus.NEW  # never seen in the window


class HistoryClassifier:
    """Classify findings' status against the project's bounded run history."""

    def __init__(
        self, session: AsyncSession, *, window: int = DEFAULT_HISTORY_WINDOW
    ) -> None:
        self._session = session
        self._runs = RunRepository(session)
        self._findings = FindingRepository(session)
        self._window = window

    async def classify(self, project_id: uuid.UUID, finding: Finding) -> FindingStatus:
        """The history status of one finding (project-scoped, read-only)."""
        prior_ids = await self._runs.prior_run_ids(
            project_id, finding.run_id, limit=self._window
        )
        with_key = await self._findings.run_ids_with_key(
            project_id, prior_ids, finding.root_cause_key
        )
        presence = [run_id in with_key for run_id in prior_ids]  # oldest → newest
        return classify_history(presence)

    async def classify_and_store(
        self, project_id: uuid.UUID, finding: Finding
    ) -> Finding:
        """Compute + persist one finding's status."""
        finding.status = (await self.classify(project_id, finding)).value
        await self._session.flush()
        return finding

    async def classify_run(
        self, project_id: uuid.UUID, run_id: uuid.UUID
    ) -> list[Finding]:
        """Classify + persist the status of every finding in a run."""
        findings = await self._findings.list_for_run(project_id, run_id)
        for finding in findings:
            await self.classify_and_store(project_id, finding)
        logger.info(
            "reporting.findings_classified",
            extra={
                "project_id": str(project_id),
                "run_id": str(run_id),
                "findings": len(findings),
            },
        )
        return findings
