"""Shared finding → wire-shape builders (run dashboard + findings inbox).

One place that turns a ``Finding`` + its batched detail + triage record into the
``FindingResponse`` the UI renders, so the run dashboard and the open-findings
inbox return an identical shape (ADR-0028).
"""

from __future__ import annotations

from app.models.enums import TriageStatus
from app.models.finding import Finding
from app.models.finding_triage import FindingTriage
from app.reporting import FindingDetail

from .schemas import (
    EvidenceItem,
    FindingHistory,
    FindingLocation,
    FindingResponse,
    TriageInfo,
)


def triage_info(record: FindingTriage | None) -> TriageInfo:
    """The current disposition, or the open default when nothing is triaged."""
    if record is None:
        return TriageInfo(status=TriageStatus.OPEN.value)
    return TriageInfo(
        status=record.status.value, note=record.note, triaged_at=record.triaged_at
    )


def build_finding_response(
    finding: Finding, detail: FindingDetail, triage: FindingTriage | None
) -> FindingResponse:
    return FindingResponse(
        id=finding.id,
        project_id=finding.project_id,
        run_id=finding.run_id,
        root_cause_key=finding.root_cause_key,
        title=finding.title,
        layer=finding.layer.value,
        severity=finding.severity,
        status=finding.status,
        oracle_source=finding.oracle_source.value,
        explains_count=finding.explains_count,
        confidence_mixed=finding.confidence_mixed,
        expected=dict(finding.expected),
        location=FindingLocation.model_validate(detail.location),
        evidence=[EvidenceItem.model_validate(item) for item in detail.evidence],
        history=FindingHistory.model_validate(detail.history),
        evidence_ref=finding.evidence_ref,
        triage=triage_info(triage),
    )
