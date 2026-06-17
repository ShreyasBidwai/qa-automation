"""Typed repository errors (Standards §7 — explicit, no bare except)."""

from __future__ import annotations


class RepositoryError(Exception):
    """Base class for repository-layer failures."""


class EdgeIntegrityError(RepositoryError):
    """An edge references a node that is missing or in a different project.

    Tenancy is enforced here (not in the model): both endpoints of an edge must
    be existing nodes within the edge's own project (Standards §5, §14).
    """
