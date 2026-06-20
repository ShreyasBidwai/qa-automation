"""Finding-detail field assembly — surface what the engine already computed.

The finding-detail drawer needs three things the summary ``FindingResponse``
didn't carry: the **location** (the deepest-node anchor + the cross-layer blast
path), the **evidence** (each failing test's "what failed" line and the
``oracle_source`` that says how much to trust it), and the **history** (the T7.4
classification plus how often/when the bug has been seen).

None of this is new data — it's read back from finding assembly
(``Finding.location``), the ``finding_results`` → ``results`` → ``test_cases``
join, and the cross-run presence the history classifier already derives. The pure
mappers here are deterministic and DB-free (so they unit-test directly);
``FindingDetailReader`` batches every read so a whole run's findings cost a fixed
number of queries, never one-per-finding (Standards §5, §14).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Outcome
from app.models.finding import Finding
from app.repositories.finding_repository import FindingRepository
from app.repositories.finding_result_repository import FindingResultRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_repository import RunRepository
from app.repositories.test_case_repository import TestCaseRepository

from .history import DEFAULT_HISTORY_WINDOW

# --- pure field mappers (deterministic, DB-free) ----------------------------


def location_anchor(location: Mapping[str, Any]) -> dict[str, Any]:
    """The deepest-node anchor of a location: table → endpoint → page (ADR-0021).

    Mirrors the assembler's grouping anchor, structured for display:
    ``node_type`` (a ``NodeKind`` value), the ``identifier`` (node name), and a
    human ``label``. An empty/unresolved location yields a typed "not resolved".
    """
    tables = [str(t) for t in (location.get("tables") or [])]
    endpoints = [str(e) for e in (location.get("endpoints") or [])]
    page = location.get("page")
    if tables:
        identifier = ", ".join(sorted(tables))
        return {"node_type": "table", "identifier": identifier, "label": identifier}
    if endpoints:
        identifier = ", ".join(sorted(endpoints))
        return {"node_type": "endpoint", "identifier": identifier, "label": identifier}
    if page:
        return {"node_type": "page", "identifier": str(page), "label": str(page)}
    return {"node_type": None, "identifier": None, "label": "Location not resolved"}


def location_payload(location: Mapping[str, Any]) -> dict[str, Any]:
    """The anchor plus the full cross-layer blast path the ribbon renders."""
    return {
        "anchor": location_anchor(location),
        "page": location.get("page"),
        "endpoints": [str(e) for e in (location.get("endpoints") or [])],
        "tables": [str(t) for t in (location.get("tables") or [])],
    }


def evidence_summary(outcome: Outcome, expected: Mapping[str, Any]) -> str:
    """A short, deterministic "what failed" line from the case's oracle + outcome.

    A reference + summary, not a log dump: the expected HTTP status and the
    assertion kinds that were checked, prefixed by how the result ended.
    """
    bits: list[str] = []
    status = expected.get("status")
    if status is not None:
        bits.append(f"expected status {status}")
    assertions = expected.get("assertions")
    if isinstance(assertions, list):
        kinds = sorted(
            {
                str(a["kind"])
                for a in assertions
                if isinstance(a, Mapping) and a.get("kind") is not None
            }
        )
        if kinds:
            bits.append("checks " + ", ".join(kinds))
    detail = "; ".join(bits) if bits else "no recorded expectation"
    verb = "Errored" if outcome is Outcome.ERROR else "Failed"
    return f"{verb} — {detail}"


def history_payload(
    classification: str,
    prior_run_ids_oldest_first: Sequence[uuid.UUID],
    run_ids_with_key: frozenset[uuid.UUID] | set[uuid.UUID],
    current_run_id: uuid.UUID,
) -> dict[str, Any]:
    """The classification plus the supporting cross-run fields it derives from.

    ``occurrence_count`` counts the runs in the window that carried this finding,
    including the current one (it is present now by definition). ``first_seen_run``
    is the earliest such run in the window (the current run if it never appeared
    before); ``last_seen_run`` is the current run.
    """
    prior_with_key = [
        run_id for run_id in prior_run_ids_oldest_first if run_id in run_ids_with_key
    ]
    return {
        "classification": classification,
        "occurrence_count": len(prior_with_key) + 1,
        "first_seen_run": prior_with_key[0] if prior_with_key else current_run_id,
        "last_seen_run": current_run_id,
    }


# --- batched reader ---------------------------------------------------------


@dataclass(frozen=True)
class FindingDetail:
    """The widened detail for one finding (location + evidence + history)."""

    location: dict[str, Any]
    evidence: list[dict[str, Any]]
    history: dict[str, Any]


class FindingDetailReader:
    """Assemble widened detail for a run's findings with batched reads (no N+1)."""

    def __init__(
        self, session: AsyncSession, *, window: int = DEFAULT_HISTORY_WINDOW
    ) -> None:
        self._members = FindingResultRepository(session)
        self._results = ResultRepository(session)
        self._cases = TestCaseRepository(session)
        self._findings = FindingRepository(session)
        self._runs = RunRepository(session)
        self._window = window

    async def detail_for(
        self,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        findings: Sequence[Finding],
    ) -> dict[uuid.UUID, FindingDetail]:
        """Widened detail keyed by finding id; a fixed query count for the run."""
        if not findings:
            return {}

        members_by_finding = await self._members_by_finding(project_id, findings)
        result_ids = {rid for ids in members_by_finding.values() for rid in ids}
        results = await self._results.get_many(project_id, result_ids)
        cases = await self._cases.get_many(
            project_id, [r.test_case_id for r in results.values()]
        )

        prior_ids = await self._runs.prior_run_ids(
            project_id, run_id, limit=self._window
        )
        runs_by_key = await self._findings.runs_by_key(
            project_id, prior_ids, [f.root_cause_key for f in findings]
        )

        detail: dict[uuid.UUID, FindingDetail] = {}
        for finding in findings:
            evidence = self._evidence_for(
                members_by_finding.get(finding.id, []), results, cases, finding
            )
            detail[finding.id] = FindingDetail(
                location=location_payload(finding.location),
                evidence=evidence,
                history=history_payload(
                    finding.status,
                    prior_ids,
                    runs_by_key.get(finding.root_cause_key, set()),
                    run_id,
                ),
            )
        return detail

    async def _members_by_finding(
        self, project_id: uuid.UUID, findings: Sequence[Finding]
    ) -> dict[uuid.UUID, list[uuid.UUID]]:
        memberships = await self._members.list_for_findings(
            project_id, [f.id for f in findings]
        )
        by_finding: dict[uuid.UUID, list[uuid.UUID]] = {}
        for member in memberships:
            by_finding.setdefault(member.finding_id, []).append(member.result_id)
        # A finding always has its representative result even if the membership
        # join is empty (defensive — real assembly always writes the rows).
        for finding in findings:
            by_finding.setdefault(finding.id, [finding.result_id])
        return by_finding

    @staticmethod
    def _evidence_for(
        result_ids: Sequence[uuid.UUID],
        results: Mapping[uuid.UUID, Any],
        cases: Mapping[uuid.UUID, Any],
        finding: Finding,
    ) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        for result_id in result_ids:
            result = results.get(result_id)
            if result is None:
                continue
            case = cases.get(result.test_case_id)
            oracle = case.oracle_source.value if case else finding.oracle_source.value
            expected = case.expected if case else {}
            evidence.append(
                {
                    "summary": evidence_summary(result.outcome, expected),
                    "oracle_source": oracle,
                    "reference": result.evidence_ref,
                }
            )
        return evidence
