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


class MergeError(ServiceError):
    """A re-generation could not be reconciled against existing cases.

    Raised when a candidate lacks the ``case_key`` needed to match, or when a key
    resolves to more than one current lineage (an invariant violation surfaced
    loudly rather than silently clobbering one).
    """


class ProposalAlreadyResolvedError(ServiceError):
    """A proposal was accepted/rejected but is no longer pending.

    Resolution is terminal: once a proposal's ``proposal_status`` is ``accepted``
    or ``rejected``, accepting or rejecting it again is rejected rather than
    silently re-applied (which could demote the wrong current version or rewrite
    provenance). The boundary maps it to 409 Conflict.
    """
