"""Reporting + the Sprint 1 walking-skeleton orchestration (PRD §10, plan §1).

Summarizes a run in ~10 oracle-honest lines, persists a coverage row, and
exposes ``run_walking_skeleton`` — the single entrypoint that chains
extract -> generate -> execute -> report for one endpoint.
"""

from __future__ import annotations

from .errors import FindingAssemblyError, ReportingError
from .finding_assembler import (
    FindingAssembler,
    LocationResolver,
    root_cause_key,
    strongest_oracle,
)
from .finding_detail import (
    FindingDetail,
    FindingDetailReader,
    evidence_summary,
    history_payload,
    location_anchor,
    location_payload,
)
from .history import HistoryClassifier, classify_history
from .orchestrator import EndpointExtractor, run_walking_skeleton
from .report import (
    OracleBreakdown,
    RunReport,
    build_report,
    persist_coverage,
    summarize,
)
from .scoring import (
    ImpactResolver,
    SeverityScorer,
    blast_radius,
    rank_findings,
    rank_key,
    score_severity,
)

__all__ = [
    "EndpointExtractor",
    "FindingAssembler",
    "FindingAssemblyError",
    "FindingDetail",
    "FindingDetailReader",
    "HistoryClassifier",
    "ImpactResolver",
    "LocationResolver",
    "OracleBreakdown",
    "ReportingError",
    "RunReport",
    "SeverityScorer",
    "blast_radius",
    "build_report",
    "classify_history",
    "evidence_summary",
    "history_payload",
    "location_anchor",
    "location_payload",
    "persist_coverage",
    "rank_findings",
    "rank_key",
    "root_cause_key",
    "run_walking_skeleton",
    "score_severity",
    "strongest_oracle",
    "summarize",
]
