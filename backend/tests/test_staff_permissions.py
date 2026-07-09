"""Staff RBAC (ADR-0068): the cross-tenant operator-console permission matrix and
its single enforcement path. Pure/hermetic — no DB, no HTTP."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.staff_authz import authorize_staff
from app.core.staff_permissions import StaffPermission, staff_role_can
from app.models.enums import StaffRole
from app.models.user import User

_MUTATIONS = {
    StaffPermission.MANAGE_JOBS,
    StaffPermission.MANAGE_TENANTS,
    StaffPermission.MANAGE_USERS,
    StaffPermission.MANAGE_BILLING,
    StaffPermission.IMPERSONATE,
}
_READS = set(StaffPermission) - _MUTATIONS


def _staff(role: StaffRole | None) -> User:
    return User(email="s@e.test", password_hash="x", staff_role=role)


def test_superadmin_can_do_everything() -> None:
    for perm in StaffPermission:
        assert staff_role_can(StaffRole.SUPERADMIN, perm)


def test_read_only_ops_mutates_nothing() -> None:
    for perm in StaffPermission:
        assert staff_role_can(StaffRole.READ_ONLY_OPS, perm) is (perm not in _MUTATIONS)


def test_every_role_shares_the_read_only_base() -> None:
    for role in StaffRole:
        for perm in _READS:
            assert staff_role_can(role, perm), f"{role} should read {perm}"


def test_separation_of_duties_support_vs_billing() -> None:
    # support acts on jobs + impersonates, but never touches money.
    assert staff_role_can(StaffRole.SUPPORT, StaffPermission.MANAGE_JOBS)
    assert staff_role_can(StaffRole.SUPPORT, StaffPermission.IMPERSONATE)
    assert not staff_role_can(StaffRole.SUPPORT, StaffPermission.MANAGE_BILLING)
    # billing owns money, but not jobs or impersonation.
    assert staff_role_can(StaffRole.BILLING, StaffPermission.MANAGE_BILLING)
    assert not staff_role_can(StaffRole.BILLING, StaffPermission.MANAGE_JOBS)
    assert not staff_role_can(StaffRole.BILLING, StaffPermission.IMPERSONATE)


def test_authorize_staff_rejects_non_staff() -> None:
    with pytest.raises(HTTPException) as exc:
        authorize_staff(_staff(None), StaffPermission.VIEW_OPS)
    assert exc.value.status_code == 403


def test_authorize_staff_rejects_insufficient_role() -> None:
    with pytest.raises(HTTPException) as exc:
        authorize_staff(_staff(StaffRole.READ_ONLY_OPS), StaffPermission.MANAGE_JOBS)
    assert exc.value.status_code == 403


def test_authorize_staff_allows_sufficient_role() -> None:
    user = _staff(StaffRole.SUPPORT)
    assert authorize_staff(user, StaffPermission.MANAGE_JOBS) is user
