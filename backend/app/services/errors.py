"""Typed service-layer errors (Standards §7 — explicit, no bare except).

Domain errors raised by services so callers (and, later, the API boundary) can
map them to stable problem+json codes instead of leaking implementation detail.
"""

from __future__ import annotations


class ServiceError(Exception):
    """Base class for service-layer (domain) failures."""


class TestCaseNotFoundError(ServiceError):
    """No matching test case for the requested (project, lineage[, version]).

    Covers both an unknown lineage and an unknown version within a lineage; the
    boundary maps it to 404. Tenancy is part of the match — a lineage in another
    project is "not found", never readable across the project boundary.
    """


class InvalidEditError(ServiceError):
    """An edit named a field that is not a human-editable test-case field.

    Edits may only change case content (steps, payload, expected, oracle, …),
    never identity/lineage/provenance columns. Rejecting unknown fields at the
    boundary keeps history honest and avoids silent no-ops (Standards §13).
    """
