"""Reporting + the Sprint 1 walking-skeleton orchestration (PRD §10, plan §1).

Summarizes a run in ~10 oracle-honest lines, persists a coverage row, and
exposes ``run_walking_skeleton`` — the single entrypoint that chains
extract -> generate -> execute -> report for one endpoint.
"""

from __future__ import annotations

from .errors import ReportingError
from .orchestrator import EndpointExtractor, run_walking_skeleton
from .report import (
    OracleBreakdown,
    RunReport,
    build_report,
    persist_coverage,
    summarize,
)

__all__ = [
    "EndpointExtractor",
    "OracleBreakdown",
    "ReportingError",
    "RunReport",
    "build_report",
    "persist_coverage",
    "run_walking_skeleton",
    "summarize",
]
