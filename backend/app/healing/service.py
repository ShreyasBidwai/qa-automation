"""HealService (B8, ADR-0040) — propose honest heals, never silent, confirmable.

``scan_run`` is the post-run pass that embodies the thesis. For each newly-failing,
previously-passing test it:

  1. classifies the failure (model-free) — ASSERTION failures are real findings and
     are NEVER healed;
  2. for a LOCATION failure, re-resolves the moved target against the Brain;
  3. only above the confidence threshold, re-addresses the script (assertions
     pinned, verified structurally) and records a PROPOSED heal — flagged,
     lower-trust, the live test untouched until a human confirms;
  4. reports honest counts: N healed (review), M real findings, K unhealed.

``confirm_heal`` applies a proposed heal to the live script (raising trust);
``reject_heal`` discards it. Both are gated at the API boundary (MANAGE_PROJECT).
Re-scanning is idempotent: the same re-addressing is recorded once.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Outcome
from app.models.test_case import TestCase
from app.models.test_heal import (
    STATUS_CONFIRMED,
    STATUS_PROPOSED,
    STATUS_REJECTED,
    TestHeal,
)
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository
from app.repositories.test_heal_repository import TestHealRepository
from app.repositories.test_script_repository import TestScriptRepository

from .apply import apply_route_heal, assertions_unchanged
from .classify import FailureClass, classify_failure
from .reresolve import reresolve_route

logger = logging.getLogger("app.healing")

HEAL_KIND_ROUTE_REBIND = "route_rebind"
DEFAULT_HISTORY_WINDOW = 10
# Only the unambiguous "high" re-binding is proposed; "low" is surfaced as an
# unhealed failure (reported honestly, never auto-applied).
_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
DEFAULT_CONFIDENCE_THRESHOLD = "high"

_FAILED = (Outcome.FAIL, Outcome.ERROR)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class HealReport:
    """The outcome of scanning one run for heals — the honest summary."""

    healed: list[TestHeal] = field(default_factory=list)
    real_findings: list[uuid.UUID] = field(default_factory=list)
    unhealed: list[uuid.UUID] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        return {
            "healed": len(self.healed),
            "real_findings": len(self.real_findings),
            "unhealed": len(self.unhealed),
        }


class HealService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        window: int = DEFAULT_HISTORY_WINDOW,
        confidence_threshold: str = DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> None:
        self._session = session
        self._heals = TestHealRepository(session)
        self._results = ResultRepository(session)
        self._runs = RunRepository(session)
        self._cases = TestCaseRepository(session)
        self._scripts = TestScriptRepository(session)
        self._window = window
        self._threshold = _CONFIDENCE_RANK[confidence_threshold]

    def _confident_enough(self, confidence: str) -> bool:
        return _CONFIDENCE_RANK.get(confidence, -1) >= self._threshold

    async def scan_run(self, project_id: uuid.UUID, run_id: uuid.UUID) -> HealReport:
        """Propose heals for the newly-failing, previously-passing tests of a run."""
        report = HealReport()
        results = await self._results.list_for_run(project_id, run_id)
        prior_ids = await self._runs.prior_run_ids(
            project_id, run_id, limit=self._window
        )
        passing_before = await self._results.passing_case_ids_in_runs(
            project_id, prior_ids
        )

        # Newly-failing AND previously-passing — the only heal candidates. A test
        # that was already failing, or is brand new, is out of scope (ADR-0040).
        failures = [
            r
            for r in results
            if r.outcome in _FAILED and r.test_case_id in passing_before
        ]
        if not failures:
            return report

        cases = await self._cases.get_many(
            project_id, {r.test_case_id for r in failures}
        )
        for result in failures:
            test_case = cases.get(result.test_case_id)
            if test_case is None:
                report.unhealed.append(result.test_case_id)
                continue

            failure_class = classify_failure(result.outcome, result.message)
            if failure_class is not FailureClass.LOCATION:
                # ASSERTION (reached, value/behaviour wrong) → a real finding. The
                # load-bearing safety rule: this is NEVER healed.
                report.real_findings.append(result.test_case_id)
                continue

            heal = await self._propose(project_id, run_id, test_case)
            if heal is None:
                report.unhealed.append(result.test_case_id)
            else:
                report.healed.append(heal)

        logger.info(
            "healing.scan_completed",
            extra={
                "project_id": str(project_id),
                "run_id": str(run_id),
                **report.summary,
            },
        )
        return report

    async def _propose(
        self, project_id: uuid.UUID, run_id: uuid.UUID, test_case: TestCase
    ) -> TestHeal | None:
        """Re-resolve, re-address (assertions pinned), and record one heal — or None.

        Returns ``None`` (reported as unhealed) when the target can't be re-bound
        confidently, the script's addressing can't be located, or re-addressing
        would disturb the assertions (the structural refusal).
        """
        preconditions = test_case.preconditions or {}
        resolution = await reresolve_route(
            self._session, project_id=project_id, preconditions=preconditions
        )
        if resolution is None or not self._confident_enough(resolution.confidence):
            return None

        scripts = await self._scripts.list_for_test_case(project_id, test_case.id)
        if not scripts:
            return None
        original = scripts[-1].code  # the current script for this case
        healed_code = apply_route_heal(
            original, resolution.old_path, resolution.new_path
        )
        if healed_code == original:
            return None  # the addressing isn't in the script → can't heal it
        if not assertions_unchanged(original, healed_code):
            # Defense in depth: a heal must never alter an assertion. If it would,
            # we refuse rather than risk healing past a real expectation.
            logger.warning(
                "healing.assertion_guard_tripped",
                extra={"test_case_id": str(test_case.id)},
            )
            return None

        # Idempotent: the same (case, before, after) is recorded once.
        existing = await self._heals.find_dedup(
            project_id, test_case.id, resolution.old_path, resolution.new_path
        )
        if existing is not None:
            return existing

        return await self._heals.add(
            TestHeal(
                project_id=project_id,
                run_id=run_id,
                test_case_id=test_case.id,
                kind=HEAL_KIND_ROUTE_REBIND,
                failure_class=FailureClass.LOCATION.value,
                before_addr=resolution.old_path,
                after_addr=resolution.new_path,
                rationale=resolution.rationale,
                confidence=resolution.confidence,
                status=STATUS_PROPOSED,
                healed_code=healed_code,
            )
        )

    async def confirm_heal(
        self, project_id: uuid.UUID, heal_id: uuid.UUID, *, resolved_by: str
    ) -> TestHeal | None:
        """Apply a proposed heal to the live script and restore trust.

        Writes the re-addressed code onto the test's current script (assertions
        already proven identical) and marks the heal confirmed. A no-op if the heal
        is missing or already resolved.
        """
        heal = await self._heals.get(project_id, heal_id)
        if heal is None or heal.status != STATUS_PROPOSED:
            return heal
        scripts = await self._scripts.list_for_test_case(project_id, heal.test_case_id)
        if scripts:
            scripts[-1].code = heal.healed_code  # apply the re-addressing
        heal.status = STATUS_CONFIRMED
        heal.resolved_by = resolved_by
        heal.resolved_at = _now()
        await self._session.flush()
        return heal

    async def reject_heal(
        self, project_id: uuid.UUID, heal_id: uuid.UUID, *, resolved_by: str
    ) -> TestHeal | None:
        """Discard a proposed heal — the live test is left exactly as it was."""
        heal = await self._heals.get(project_id, heal_id)
        if heal is None or heal.status != STATUS_PROPOSED:
            return heal
        heal.status = STATUS_REJECTED
        heal.resolved_by = resolved_by
        heal.resolved_at = _now()
        await self._session.flush()
        return heal
