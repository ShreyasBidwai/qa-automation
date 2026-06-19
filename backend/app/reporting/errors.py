"""Typed reporting errors (Standards §7 — explicit, no bare except)."""

from __future__ import annotations


class ReportingError(Exception):
    """Base class for reporting / walking-skeleton orchestration failures."""


class FindingAssemblyError(ReportingError):
    """A run result could not be assembled into a Finding.

    Raised when a result references a test case that is not in the project (a
    tenancy/integrity failure) — surfaced loudly rather than dropped (Standards §7).
    """
