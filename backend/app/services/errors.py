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


class InvalidCaseSpecError(ServiceError):
    """A human-authoring spec is malformed (Mode A).

    Raised when an authored case cannot be built from the spec — e.g. a missing
    HTTP method or URI, or an out-of-range expected status. Distinct from
    ``InvalidEditError`` (which guards *edits* to existing cases): this guards the
    initial authoring input. The boundary maps it to 422.
    """


class EmailAlreadyRegisteredError(ServiceError):
    """Sign-up with an email that already has an account. Boundary → 409."""


class InvalidCredentialsError(ServiceError):
    """Sign-in with an unknown email or wrong password. Boundary → 401.

    Deliberately does not distinguish the two cases (no account enumeration).
    """


class InvalidResetTokenError(ServiceError):
    """A password-reset token is unknown, already used, or expired. → 400.

    Single error for all three so a caller cannot probe token validity/state.
    """


class InvalidInviteError(ServiceError):
    """An org invite token is unknown, already accepted, or expired (B3). → 400.

    One error for all three (no probing token validity/state), mirroring
    ``InvalidResetTokenError`` (ADR-0030/0033).
    """


class AlreadyMemberError(ServiceError):
    """An invite targets an email whose account is already in the org. → 409."""


class MemberNotFoundError(ServiceError):
    """A member-management action named a user who is not in the org. → 404."""


class LastOwnerError(ServiceError):
    """Demoting/removing the last owner would orphan the org (ADR-0033). → 409."""


class RoleManagementError(ServiceError):
    """An admin tried to manage an owner or grant the owner role (ADR-0033). → 403.

    Only an owner may create/modify/remove owners; an admin cannot.
    """


class CannotDeletePersonalOrgError(ServiceError):
    """A personal (per-user) org cannot be deleted (ADR-0032). → 400."""


class ProposalAlreadyResolvedError(ServiceError):
    """A proposal was accepted/rejected but is no longer pending.

    Resolution is terminal: once a proposal's ``proposal_status`` is ``accepted``
    or ``rejected``, accepting or rejecting it again is rejected rather than
    silently re-applied (which could demote the wrong current version or rewrite
    provenance). The boundary maps it to 409 Conflict.
    """
