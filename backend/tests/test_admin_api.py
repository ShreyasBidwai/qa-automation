"""Admin console API (ADR-0068): /admin/me identity + /admin/audit trail, both
gated by staff RBAC. A normal (non-staff) user is 403 everywhere here."""

from __future__ import annotations

import uuid

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import StaffRole
from app.models.user import User
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.staff_audit_repository import StaffAuditRepository


async def _signup(client: httpx.AsyncClient) -> tuple[dict[str, str], str]:
    email = f"admin-{uuid.uuid4().hex[:10]}@e.test"
    token = (
        await client.post(
            "/api/v1/auth/signup", json={"email": email, "password": "adminpass1"}
        )
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, email


async def _promote(session: AsyncSession, email: str, role: StaffRole) -> User:
    user = (await session.scalars(select(User).where(User.email == email))).one()
    user.staff_role = role
    await session.flush()
    return user


async def test_admin_me_requires_staff(
    app_client: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    headers, _ = await _signup(client)
    resp = await client.get("/api/v1/admin/me", headers=headers)
    assert resp.status_code == 403  # a normal user is not staff


async def test_admin_me_returns_role_and_permissions(
    app_client: tuple[httpx.AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = app_client
    headers, email = await _signup(client)
    await _promote(db_session, email, StaffRole.SUPPORT)

    body = (await client.get("/api/v1/admin/me", headers=headers)).json()
    assert body["staff_role"] == "support"
    # support acts on jobs + impersonates, but never touches billing (SoD, ADR-0068).
    assert "manage_jobs" in body["permissions"]
    assert "impersonate" in body["permissions"]
    assert "manage_billing" not in body["permissions"]


async def test_admin_audit_requires_view_audit(
    app_client: tuple[httpx.AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = app_client
    headers, email = await _signup(client)
    # A non-staff user cannot read the trail.
    assert (await client.get("/api/v1/admin/audit", headers=headers)).status_code == 403
    # read_only_ops carries VIEW_AUDIT — the empty trail lists cleanly.
    await _promote(db_session, email, StaffRole.READ_ONLY_OPS)
    resp = await client.get("/api/v1/admin/audit", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_audit_repository_records_and_lists(
    app_client: tuple[httpx.AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = app_client
    _, email = await _signup(client)
    actor = await _promote(db_session, email, StaffRole.SUPERADMIN)

    repo = StaffAuditRepository(db_session)
    await repo.record(
        actor=actor,
        action="job.retry",
        target_type="job",
        target_id="abc-123",
        detail={"reason": "manual"},
    )
    entries = await repo.list(limit=50, offset=0)
    assert len(entries) == 1
    assert entries[0].action == "job.retry"
    assert entries[0].actor_email == email
    assert entries[0].detail == {"reason": "manual"}
    assert await repo.count(action="job.retry") == 1
    assert await repo.count(action="org.suspend") == 0


async def _personal_org_id(session: AsyncSession, email: str) -> uuid.UUID:
    user = (await session.scalars(select(User).where(User.email == email))).one()
    org = await OrganizationRepository(session).get_personal_org(user.id)
    assert org is not None
    return org.id


async def test_list_orgs_requires_view_tenants(
    app_client: tuple[httpx.AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = app_client
    headers, email = await _signup(client)  # signup auto-creates a personal org
    assert (await client.get("/api/v1/admin/orgs", headers=headers)).status_code == 403
    await _promote(db_session, email, StaffRole.READ_ONLY_OPS)

    body = (await client.get("/api/v1/admin/orgs", headers=headers)).json()
    assert body["total"] >= 1
    # cross-tenant: the caller's own personal org is visible, with a member count.
    assert any(o["is_personal"] and o["member_count"] >= 1 for o in body["items"])


async def test_suspend_org_requires_manage_tenants_and_audits(
    app_client: tuple[httpx.AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = app_client
    _, victim_email = await _signup(client)  # the org we will suspend
    staff_headers, staff_email = await _signup(client)
    org_id = await _personal_org_id(db_session, victim_email)

    # read_only_ops can view but NOT suspend (no MANAGE_TENANTS).
    await _promote(db_session, staff_email, StaffRole.READ_ONLY_OPS)
    r = await client.post(f"/api/v1/admin/orgs/{org_id}/suspend", headers=staff_headers)
    assert r.status_code == 403

    # superadmin can — and it audits.
    await _promote(db_session, staff_email, StaffRole.SUPERADMIN)
    r = await client.post(f"/api/v1/admin/orgs/{org_id}/suspend", headers=staff_headers)
    assert r.status_code == 200 and r.json()["suspended"] is True

    audit = (
        await client.get("/api/v1/admin/audit?action=org.suspend", headers=staff_headers)
    ).json()
    assert audit["total"] == 1
    assert audit["items"][0]["target_id"] == str(org_id)

    # reactivate lifts it.
    r = await client.post(
        f"/api/v1/admin/orgs/{org_id}/reactivate", headers=staff_headers
    )
    assert r.status_code == 200 and r.json()["suspended"] is False


async def test_get_org_detail_lists_members(
    app_client: tuple[httpx.AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = app_client
    headers, email = await _signup(client)
    await _promote(db_session, email, StaffRole.SUPERADMIN)
    org_id = await _personal_org_id(db_session, email)

    body = (await client.get(f"/api/v1/admin/orgs/{org_id}", headers=headers)).json()
    assert body["id"] == str(org_id)
    assert body["member_count"] == 1
    assert body["members"][0]["email"] == email
    assert body["members"][0]["role"] == "owner"  # personal-org creator is owner


async def _user_id(session: AsyncSession, email: str) -> uuid.UUID:
    return (await session.scalars(select(User).where(User.email == email))).one().id


async def test_list_users_requires_view_users(
    app_client: tuple[httpx.AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = app_client
    headers, email = await _signup(client)
    assert (await client.get("/api/v1/admin/users", headers=headers)).status_code == 403
    await _promote(db_session, email, StaffRole.READ_ONLY_OPS)

    body = (await client.get("/api/v1/admin/users", headers=headers)).json()
    assert body["total"] >= 1
    assert any(u["email"] == email and u["org_count"] >= 1 for u in body["items"])


async def test_deactivate_user_requires_manage_users_and_guards_self(
    app_client: tuple[httpx.AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = app_client
    _, victim_email = await _signup(client)
    staff_headers, staff_email = await _signup(client)
    victim_id = await _user_id(db_session, victim_email)

    # read_only_ops lacks MANAGE_USERS.
    await _promote(db_session, staff_email, StaffRole.READ_ONLY_OPS)
    r = await client.post(
        f"/api/v1/admin/users/{victim_id}/deactivate", headers=staff_headers
    )
    assert r.status_code == 403

    await _promote(db_session, staff_email, StaffRole.SUPERADMIN)
    # cannot deactivate self.
    staff_id = await _user_id(db_session, staff_email)
    r = await client.post(
        f"/api/v1/admin/users/{staff_id}/deactivate", headers=staff_headers
    )
    assert r.status_code == 400
    # can deactivate another user — and it audits.
    r = await client.post(
        f"/api/v1/admin/users/{victim_id}/deactivate", headers=staff_headers
    )
    assert r.status_code == 200 and r.json()["is_active"] is False
    audit = (
        await client.get(
            "/api/v1/admin/audit?action=user.deactivate", headers=staff_headers
        )
    ).json()
    assert audit["total"] == 1 and audit["items"][0]["target_id"] == str(victim_id)


async def test_set_staff_role_grants_revokes_and_validates(
    app_client: tuple[httpx.AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = app_client
    _, target_email = await _signup(client)
    staff_headers, staff_email = await _signup(client)
    await _promote(db_session, staff_email, StaffRole.SUPERADMIN)
    target_id = await _user_id(db_session, target_email)
    url = f"/api/v1/admin/users/{target_id}/staff-role"

    # invalid role name is rejected against the allow-list.
    bad = await client.post(url, json={"staff_role": "root"}, headers=staff_headers)
    assert bad.status_code == 422

    # grant support, then revoke.
    granted = await client.post(
        url, json={"staff_role": "support"}, headers=staff_headers
    )
    assert granted.status_code == 200 and granted.json()["staff_role"] == "support"
    revoked = await client.post(
        url, json={"staff_role": None}, headers=staff_headers
    )
    assert revoked.status_code == 200 and revoked.json()["staff_role"] is None

    # cannot change your own staff role.
    staff_id = await _user_id(db_session, staff_email)
    own = await client.post(
        f"/api/v1/admin/users/{staff_id}/staff-role",
        json={"staff_role": "read_only_ops"},
        headers=staff_headers,
    )
    assert own.status_code == 400


async def test_get_user_detail_lists_orgs(
    app_client: tuple[httpx.AsyncClient, FastAPI],
    db_session: AsyncSession,
) -> None:
    client, _ = app_client
    headers, email = await _signup(client)
    await _promote(db_session, email, StaffRole.SUPERADMIN)
    user_id = await _user_id(db_session, email)

    body = (await client.get(f"/api/v1/admin/users/{user_id}", headers=headers)).json()
    assert body["email"] == email
    assert body["staff_role"] == "superadmin"
    assert body["orgs"][0]["role"] == "owner"  # owner of their personal org
