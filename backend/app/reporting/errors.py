"""Typed reporting errors (Standards §7 — explicit, no bare except)."""

from __future__ import annotations


class ReportingError(Exception):
    """Base class for reporting / walking-skeleton orchestration failures."""
