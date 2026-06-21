"""The RBAC matrix (ADR-0033) — owner ⊇ admin ⊇ member ⊇ viewer.

Pins the role→permission table directly so a change to the matrix is a deliberate,
visible edit (and the enforcement tests in test_rbac.py exercise it end-to-end).
"""

from __future__ import annotations

from app.core.permissions import Permission, role_can
from app.models.enums import OrgRole

_EXPECTED: dict[OrgRole, set[Permission]] = {
    OrgRole.OWNER: set(Permission),  # everything, incl. MANAGE_ORG
    OrgRole.ADMIN: {
        Permission.VIEW,
        Permission.RUN,
        Permission.TRIAGE,
        Permission.MANAGE_PROJECT,
        Permission.MANAGE_MEMBERS,
    },
    OrgRole.MEMBER: {
        Permission.VIEW,
        Permission.RUN,
        Permission.TRIAGE,
        Permission.MANAGE_PROJECT,
    },
    OrgRole.VIEWER: {Permission.VIEW},
}


def test_matrix_is_exactly_as_specified() -> None:
    for role in OrgRole:
        for permission in Permission:
            assert role_can(role, permission) is (permission in _EXPECTED[role]), (
                role,
                permission,
            )


def test_only_owner_manages_org_and_only_owner_admin_manage_members() -> None:
    assert role_can(OrgRole.OWNER, Permission.MANAGE_ORG)
    assert not role_can(OrgRole.ADMIN, Permission.MANAGE_ORG)
    assert role_can(OrgRole.ADMIN, Permission.MANAGE_MEMBERS)
    assert not role_can(OrgRole.MEMBER, Permission.MANAGE_MEMBERS)


def test_viewer_is_read_only() -> None:
    assert role_can(OrgRole.VIEWER, Permission.VIEW)
    assert not role_can(OrgRole.VIEWER, Permission.RUN)
    assert not role_can(OrgRole.VIEWER, Permission.TRIAGE)
    assert not role_can(OrgRole.VIEWER, Permission.MANAGE_PROJECT)
