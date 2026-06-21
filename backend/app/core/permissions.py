"""The RBAC permission matrix (B3, ADR-0033) — the single source of truth.

Pure data + one predicate, no DB and no HTTP. A role maps to the set of actions it
may perform; ``role_can`` answers "may this role do this?". The two target-aware
rules (only an owner manages owners; an org keeps ≥1 owner) cannot be expressed as
a role→permission cell and live with the member-management logic instead.
"""

from __future__ import annotations

import enum

from app.models.enums import OrgRole


class Permission(str, enum.Enum):
    """An action gated by RBAC. Endpoints require one of these."""

    VIEW = "view"  # read projects / runs / findings
    RUN = "run"  # create a run, ingest
    TRIAGE = "triage"  # triage findings (single + bulk)
    MANAGE_PROJECT = "manage_project"  # create / update / delete a project
    MANAGE_MEMBERS = "manage_members"  # invite, change role, remove a member
    MANAGE_ORG = "manage_org"  # rename / delete the org


_CONTRIBUTOR: frozenset[Permission] = frozenset(
    {
        Permission.VIEW,
        Permission.RUN,
        Permission.TRIAGE,
        Permission.MANAGE_PROJECT,
    }
)

# Role → allowed permissions (ADR-0033). owner ⊇ admin ⊇ member ⊇ viewer.
_MATRIX: dict[OrgRole, frozenset[Permission]] = {
    OrgRole.OWNER: frozenset(Permission),
    OrgRole.ADMIN: _CONTRIBUTOR | {Permission.MANAGE_MEMBERS},
    OrgRole.MEMBER: _CONTRIBUTOR,
    OrgRole.VIEWER: frozenset({Permission.VIEW}),
}


def role_can(role: OrgRole, permission: Permission) -> bool:
    """True iff ``role`` is permitted to perform ``permission`` (ADR-0033)."""
    return permission in _MATRIX[role]
