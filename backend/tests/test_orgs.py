"""Teams: org CRUD, invites, and member management (B3, ADR-0032/0033).

API-level happy + denial paths through the in-process client (with a capturing
mailer so invite tokens are observable without logging), plus a service-level test
for the time-controlled expiry case. The app client commits to the shared test DB,
so every persona uses a unique email.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.user import User
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository
from app.services.errors import (
    AlreadyMemberError,
    CannotDeletePersonalOrgError,
    InvalidInviteError,
    LastOwnerError,
    MemberNotFoundError,
    RoleManagementError,
)
from app.services.org_service import OrgService


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _email() -> str:
    return f"org-{uuid.uuid4().hex[:12]}@example.test"


class _CapturingMailer:
    def __init__(self) -> None:
        self.invites: list[dict[str, str]] = []
        self.resets: list[tuple[str, str]] = []

    async def send_password_reset(self, *, email: str, token: str) -> None:
        self.resets.append((email, token))

    async def send_org_invite(
        self, *, email: str, token: str, org_name: str, role: str
    ) -> None:
        self.invites.append(
            {"email": email, "token": token, "org_name": org_name, "role": role}
        )


@pytest_asyncio.fixture
async def orgs(
    app_client: tuple[AsyncClient, FastAPI],
) -> tuple[AsyncClient, FastAPI, _CapturingMailer]:
    client, app = app_client
    mailer = _CapturingMailer()
    app.state.mailer = mailer
    return client, app, mailer


async def _signup(client: AsyncClient) -> tuple[str, uuid.UUID, str]:
    email = _email()
    resp = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": "passw0rd1"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["access_token"], uuid.UUID(body["user"]["id"]), email


async def _make_team(client: AsyncClient, token: str, name: str = "Acme") -> uuid.UUID:
    resp = await client.post("/api/v1/orgs", json={"name": name}, headers=_h(token))
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == "owner" and resp.json()["is_personal"] is False
    return uuid.UUID(resp.json()["id"])


async def _invite(
    client: AsyncClient,
    mailer: _CapturingMailer,
    *,
    actor: str,
    org_id: uuid.UUID,
    email: str,
    role: str = "member",
) -> str:
    resp = await client.post(
        f"/api/v1/orgs/{org_id}/invites",
        json={"email": email, "role": role},
        headers=_h(actor),
    )
    assert resp.status_code == 201, resp.text
    assert "token" not in resp.text  # the secret is emailed, never returned
    return mailer.invites[-1]["token"]


async def _accept(client: AsyncClient, *, token: str, as_token: str):
    return await client.post(
        "/api/v1/invites/accept", json={"token": token}, headers=_h(as_token)
    )


# --- org CRUD ---------------------------------------------------------------


async def test_create_and_list_orgs(
    orgs: tuple[AsyncClient, FastAPI, _CapturingMailer],
) -> None:
    client, _, _ = orgs
    token, _, _ = await _signup(client)
    team = await _make_team(client, token, name="Acme")

    listing = (await client.get("/api/v1/orgs", headers=_h(token))).json()
    by_id = {item["id"]: item for item in listing["items"]}
    assert str(team) in by_id and by_id[str(team)]["role"] == "owner"
    # The signup-created personal org is also present.
    assert any(item["is_personal"] for item in listing["items"])
    assert listing["total"] == 2


async def test_delete_org_owner_only_and_not_personal(
    orgs: tuple[AsyncClient, FastAPI, _CapturingMailer],
) -> None:
    client, _, mailer = orgs
    owner, _, _ = await _signup(client)
    team = await _make_team(client, owner)

    # A personal org cannot be deleted.
    listing = (await client.get("/api/v1/orgs", headers=_h(owner))).json()
    personal = next(o["id"] for o in listing["items"] if o["is_personal"])
    assert (
        await client.delete(f"/api/v1/orgs/{personal}", headers=_h(owner))
    ).status_code == 400

    # An admin cannot delete the team; the owner can.
    admin, _, admin_email = await _signup(client)
    token = await _invite(
        client, mailer, actor=owner, org_id=team, email=admin_email, role="admin"
    )
    await _accept(client, token=token, as_token=admin)
    assert (
        await client.delete(f"/api/v1/orgs/{team}", headers=_h(admin))
    ).status_code == 403
    assert (
        await client.delete(f"/api/v1/orgs/{team}", headers=_h(owner))
    ).status_code == 204
    # Gone: the owner is no longer a member of anything by that id → 404.
    assert (
        await client.get(f"/api/v1/orgs/{team}", headers=_h(owner))
    ).status_code == 404


# --- invites ----------------------------------------------------------------


async def test_invite_accept_existing_user_and_single_use(
    orgs: tuple[AsyncClient, FastAPI, _CapturingMailer],
) -> None:
    client, _, mailer = orgs
    owner, _, _ = await _signup(client)
    team = await _make_team(client, owner)
    invitee, invitee_id, invitee_email = await _signup(client)

    token = await _invite(client, mailer, actor=owner, org_id=team, email=invitee_email)
    accept = await client.post(
        "/api/v1/invites/accept", json={"token": token}, headers=_h(invitee)
    )
    assert accept.status_code == 200
    assert accept.json() == {"org_id": str(team), "role": "member"}

    members = (
        await client.get(f"/api/v1/orgs/{team}/members", headers=_h(owner))
    ).json()
    roles = {m["user_id"]: m["role"] for m in members["items"]}
    assert roles[str(invitee_id)] == "member"

    # Single-use: the token cannot be replayed.
    replay = await client.post(
        "/api/v1/invites/accept", json={"token": token}, headers=_h(invitee)
    )
    assert replay.status_code == 400


async def test_invite_accept_new_user(
    orgs: tuple[AsyncClient, FastAPI, _CapturingMailer],
) -> None:
    client, _, mailer = orgs
    owner, _, _ = await _signup(client)
    team = await _make_team(client, owner)

    # Invite someone with no account yet; they sign up, then accept.
    invited_email = _email()
    token = await _invite(
        client, mailer, actor=owner, org_id=team, email=invited_email, role="viewer"
    )
    newcomer, _, _ = await _signup(client)
    accept = await client.post(
        "/api/v1/invites/accept", json={"token": token}, headers=_h(newcomer)
    )
    assert accept.status_code == 200 and accept.json()["role"] == "viewer"


async def test_invite_is_role_gated(
    orgs: tuple[AsyncClient, FastAPI, _CapturingMailer],
) -> None:
    client, _, mailer = orgs
    owner, _, _ = await _signup(client)
    team = await _make_team(client, owner)
    member, _, member_email = await _signup(client)
    token = await _invite(client, mailer, actor=owner, org_id=team, email=member_email)
    await _accept(client, token=token, as_token=member)

    # A plain member lacks MANAGE_MEMBERS → 403.
    denied = await client.post(
        f"/api/v1/orgs/{team}/invites",
        json={"email": _email(), "role": "member"},
        headers=_h(member),
    )
    assert denied.status_code == 403

    # A non-member → 404 (existence not leaked).
    outsider, _, _ = await _signup(client)
    leak = await client.post(
        f"/api/v1/orgs/{team}/invites",
        json={"email": _email(), "role": "member"},
        headers=_h(outsider),
    )
    assert leak.status_code == 404


async def test_admin_cannot_invite_owner(
    orgs: tuple[AsyncClient, FastAPI, _CapturingMailer],
) -> None:
    client, _, mailer = orgs
    owner, _, _ = await _signup(client)
    team = await _make_team(client, owner)
    admin, admin_id, admin_email = await _signup(client)
    token = await _invite(
        client, mailer, actor=owner, org_id=team, email=admin_email, role="admin"
    )
    await _accept(client, token=token, as_token=admin)

    # admin may invite a member but not an owner (only owners manage owners).
    ok = await client.post(
        f"/api/v1/orgs/{team}/invites",
        json={"email": _email(), "role": "member"},
        headers=_h(admin),
    )
    assert ok.status_code == 201
    denied = await client.post(
        f"/api/v1/orgs/{team}/invites",
        json={"email": _email(), "role": "owner"},
        headers=_h(admin),
    )
    assert denied.status_code == 403

    # Pending invites are listable by a manager (the admin's own invite was
    # accepted, so only the still-open member invite remains).
    pending = (
        await client.get(f"/api/v1/orgs/{team}/invites", headers=_h(owner))
    ).json()
    assert pending["total"] == 1
    assert pending["items"][0]["accepted_at"] is None
    assert "token" not in str(pending["items"])  # never exposed


async def test_invite_existing_member_conflicts(
    orgs: tuple[AsyncClient, FastAPI, _CapturingMailer],
) -> None:
    client, _, mailer = orgs
    owner, _, _ = await _signup(client)
    team = await _make_team(client, owner)
    member, _, member_email = await _signup(client)
    token = await _invite(client, mailer, actor=owner, org_id=team, email=member_email)
    await _accept(client, token=token, as_token=member)

    dupe = await client.post(
        f"/api/v1/orgs/{team}/invites",
        json={"email": member_email, "role": "member"},
        headers=_h(owner),
    )
    assert dupe.status_code == 409


# --- member management ------------------------------------------------------


async def test_change_role_and_remove_are_gated(
    orgs: tuple[AsyncClient, FastAPI, _CapturingMailer],
) -> None:
    client, _, mailer = orgs
    owner, owner_id, _ = await _signup(client)
    team = await _make_team(client, owner)
    member, member_id, member_email = await _signup(client)
    token = await _invite(client, mailer, actor=owner, org_id=team, email=member_email)
    await _accept(client, token=token, as_token=member)

    # owner promotes member → admin.
    promote = await client.patch(
        f"/api/v1/orgs/{team}/members/{member_id}",
        json={"role": "admin"},
        headers=_h(owner),
    )
    assert promote.status_code == 200 and promote.json()["role"] == "admin"

    # The admin cannot touch the owner (only owners manage owners) → 403.
    admin_vs_owner = await client.patch(
        f"/api/v1/orgs/{team}/members/{owner_id}",
        json={"role": "member"},
        headers=_h(member),
    )
    assert admin_vs_owner.status_code == 403

    # owner removes the (now admin) member.
    removed = await client.delete(
        f"/api/v1/orgs/{team}/members/{member_id}", headers=_h(owner)
    )
    assert removed.status_code == 204
    members = (
        await client.get(f"/api/v1/orgs/{team}/members", headers=_h(owner))
    ).json()
    assert str(member_id) not in {m["user_id"] for m in members["items"]}


async def test_cannot_orphan_the_last_owner(
    orgs: tuple[AsyncClient, FastAPI, _CapturingMailer],
) -> None:
    client, _, _ = orgs
    owner, owner_id, _ = await _signup(client)
    team = await _make_team(client, owner)

    demote = await client.patch(
        f"/api/v1/orgs/{team}/members/{owner_id}",
        json={"role": "member"},
        headers=_h(owner),
    )
    assert demote.status_code == 409  # would orphan the org
    remove = await client.delete(
        f"/api/v1/orgs/{team}/members/{owner_id}", headers=_h(owner)
    )
    assert remove.status_code == 409


async def test_member_management_unknown_member_is_404(
    orgs: tuple[AsyncClient, FastAPI, _CapturingMailer],
) -> None:
    client, _, _ = orgs
    owner, _, _ = await _signup(client)
    team = await _make_team(client, owner)
    resp = await client.patch(
        f"/api/v1/orgs/{team}/members/{uuid.uuid4()}",
        json={"role": "member"},
        headers=_h(owner),
    )
    assert resp.status_code == 404


# --- service-level (time-controlled) ----------------------------------------


async def test_accept_rejects_expired_invite(db_session: AsyncSession) -> None:
    users = UserRepository(db_session)
    orgs_repo = OrganizationRepository(db_session)
    owner = await users.add(
        User(email=_email(), password_hash=hash_password("passw0rd1"))
    )
    invitee = await users.add(
        User(email=_email(), password_hash=hash_password("passw0rd1"))
    )
    org = await orgs_repo.add(Organization(name="T", is_personal=False))
    await orgs_repo.add_member(org.id, owner.id, OrgRole.OWNER)

    mailer = _CapturingMailer()
    # invite_ttl_seconds=-1 → the invite is already expired the moment it's issued.
    svc = OrgService(db_session, mailer=mailer, invite_ttl_seconds=-1)
    await svc.invite(
        org=org,
        actor_role=OrgRole.OWNER,
        email=invitee.email,
        role=OrgRole.MEMBER,
        invited_by=owner.id,
    )
    token = mailer.invites[-1]["token"]
    with pytest.raises(InvalidInviteError):
        await svc.accept_invite(token, invitee)


async def _user(db_session: AsyncSession) -> User:
    return await UserRepository(db_session).add(
        User(email=_email(), password_hash=hash_password("passw0rd1"))
    )


def _svc(
    db_session: AsyncSession, mailer: _CapturingMailer | None = None
) -> OrgService:
    return OrgService(
        db_session, mailer=mailer or _CapturingMailer(), invite_ttl_seconds=3600
    )


async def test_service_create_org_makes_creator_owner(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    org = await _svc(db_session).create_org("New Team", user)
    assert org.is_personal is False
    repo = OrganizationRepository(db_session)
    membership = await repo.get_membership(org.id, user.id)
    assert membership is not None and membership.role == OrgRole.OWNER


async def test_service_change_role_guards(db_session: AsyncSession) -> None:
    svc = _svc(db_session)
    repo = OrganizationRepository(db_session)
    owner, owner2, member = (
        await _user(db_session),
        await _user(db_session),
        await _user(db_session),
    )
    org = await repo.add(Organization(name="T", is_personal=False))
    await repo.add_member(org.id, owner.id, OrgRole.OWNER)
    await repo.add_member(org.id, member.id, OrgRole.MEMBER)
    owner_m = await repo.get_membership(org.id, owner.id)
    assert owner_m is not None

    # Unknown target → 404 domain error.
    with pytest.raises(MemberNotFoundError):
        await svc.change_role(
            org_id=org.id,
            actor=owner_m,
            target_user_id=uuid.uuid4(),
            new_role=OrgRole.ADMIN,
        )

    # owner promotes member → admin.
    promoted = await svc.change_role(
        org_id=org.id, actor=owner_m, target_user_id=member.id, new_role=OrgRole.ADMIN
    )
    assert promoted.role == OrgRole.ADMIN

    # admin may not manage an owner, nor grant the owner role.
    admin_m = await repo.get_membership(org.id, member.id)
    assert admin_m is not None
    with pytest.raises(RoleManagementError):
        await svc.change_role(
            org_id=org.id,
            actor=admin_m,
            target_user_id=owner.id,
            new_role=OrgRole.MEMBER,
        )
    with pytest.raises(RoleManagementError):
        await svc.change_role(
            org_id=org.id,
            actor=admin_m,
            target_user_id=member.id,
            new_role=OrgRole.OWNER,
        )

    # Demoting the sole owner is refused; with a second owner it succeeds.
    with pytest.raises(LastOwnerError):
        await svc.change_role(
            org_id=org.id,
            actor=owner_m,
            target_user_id=owner.id,
            new_role=OrgRole.ADMIN,
        )
    await repo.add_member(org.id, owner2.id, OrgRole.OWNER)
    demoted = await svc.change_role(
        org_id=org.id, actor=owner_m, target_user_id=owner.id, new_role=OrgRole.ADMIN
    )
    assert demoted.role == OrgRole.ADMIN


async def test_service_remove_member_guards(db_session: AsyncSession) -> None:
    svc = _svc(db_session)
    repo = OrganizationRepository(db_session)
    owner, member = await _user(db_session), await _user(db_session)
    org = await repo.add(Organization(name="T", is_personal=False))
    await repo.add_member(org.id, owner.id, OrgRole.OWNER)
    await repo.add_member(org.id, member.id, OrgRole.ADMIN)
    owner_m = await repo.get_membership(org.id, owner.id)
    admin_m = await repo.get_membership(org.id, member.id)
    assert owner_m is not None and admin_m is not None

    with pytest.raises(MemberNotFoundError):
        await svc.remove_member(
            org_id=org.id, actor=owner_m, target_user_id=uuid.uuid4()
        )
    # an admin can't remove an owner.
    with pytest.raises(RoleManagementError):
        await svc.remove_member(org_id=org.id, actor=admin_m, target_user_id=owner.id)
    # the last owner can't be removed.
    with pytest.raises(LastOwnerError):
        await svc.remove_member(org_id=org.id, actor=owner_m, target_user_id=owner.id)
    # happy: owner removes the admin.
    await svc.remove_member(org_id=org.id, actor=owner_m, target_user_id=member.id)
    assert await repo.get_membership(org.id, member.id) is None


async def test_service_accept_when_already_member_is_idempotent(
    db_session: AsyncSession,
) -> None:
    mailer = _CapturingMailer()
    svc = _svc(db_session, mailer)
    repo = OrganizationRepository(db_session)
    owner, invitee = await _user(db_session), await _user(db_session)
    org = await repo.add(Organization(name="T", is_personal=False))
    await repo.add_member(org.id, owner.id, OrgRole.OWNER)

    # Invite while they're not a member, then they join another way.
    await svc.invite(
        org=org,
        actor_role=OrgRole.OWNER,
        email=invitee.email,
        role=OrgRole.VIEWER,
        invited_by=owner.id,
    )
    token = mailer.invites[-1]["token"]
    existing = await repo.add_member(org.id, invitee.id, OrgRole.MEMBER)

    # Accepting keeps their existing (higher) role, and consumes the token.
    result = await svc.accept_invite(token, invitee)
    assert result.id == existing.id and result.role == OrgRole.MEMBER
    with pytest.raises(InvalidInviteError):
        await svc.accept_invite(token, invitee)
    # Re-inviting an existing member conflicts.
    with pytest.raises(AlreadyMemberError):
        await svc.invite(
            org=org,
            actor_role=OrgRole.OWNER,
            email=invitee.email,
            role=OrgRole.VIEWER,
            invited_by=owner.id,
        )


async def test_service_accept_invite_joins_with_invited_role(
    db_session: AsyncSession,
) -> None:
    mailer = _CapturingMailer()
    svc = _svc(db_session, mailer)
    repo = OrganizationRepository(db_session)
    owner, invitee = await _user(db_session), await _user(db_session)
    org = await repo.add(Organization(name="T", is_personal=False))
    await repo.add_member(org.id, owner.id, OrgRole.OWNER)

    await svc.invite(
        org=org,
        actor_role=OrgRole.OWNER,
        email=invitee.email,
        role=OrgRole.ADMIN,
        invited_by=owner.id,
    )
    member = await svc.accept_invite(mailer.invites[-1]["token"], invitee)
    assert member.org_id == org.id and member.role == OrgRole.ADMIN
    stored = await repo.get_membership(org.id, invitee.id)
    assert stored is not None and stored.role == OrgRole.ADMIN


async def test_service_delete_org_personal_guard(db_session: AsyncSession) -> None:
    svc = _svc(db_session)
    repo = OrganizationRepository(db_session)
    personal = await repo.add(Organization(name="P", is_personal=True))
    with pytest.raises(CannotDeletePersonalOrgError):
        await svc.delete_org(personal)

    team = await repo.add(Organization(name="Team", is_personal=False))
    await svc.delete_org(team)
    gone = (
        await db_session.scalars(select(Organization).where(Organization.id == team.id))
    ).one_or_none()
    assert gone is None
