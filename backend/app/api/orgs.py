"""Organization / membership / invite routes (B3, ADR-0032/0033).

Thin boundary: authenticate (``CurrentUser``), run the RBAC gate (``authz``), call
``OrgService``, and map domain errors to stable HTTP codes. The 404-for-outsiders /
403-for-insiders split lives in ``authz``; the target-aware rules (owner-only owner
management, last-owner guard) live in ``OrgService`` and surface as 403/409 here.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.permissions import Permission
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.organization_invite import OrganizationInvite
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.repositories.organization_invite_repository import (
    OrganizationInviteRepository,
)
from app.repositories.organization_repository import OrganizationRepository
from app.services.errors import (
    AlreadyMemberError,
    CannotDeletePersonalOrgError,
    InvalidInviteError,
    LastOwnerError,
    MemberNotFoundError,
    RoleManagementError,
)
from app.services.org_service import OrgService

from .authz import authorize_org
from .deps import CurrentUser, get_session
from .schemas import (
    InviteAccept,
    InviteAcceptResponse,
    InviteCreate,
    InviteListResponse,
    InviteResponse,
    MemberListResponse,
    MemberResponse,
    OrgCreate,
    OrgListResponse,
    OrgResponse,
    RoleUpdate,
)

router = APIRouter(prefix="/api/v1", tags=["organizations"])


def _service(request: Request, session: AsyncSession) -> OrgService:
    return OrgService(
        session,
        mailer=request.app.state.mailer,
        invite_ttl_seconds=get_settings().org_invite_ttl_seconds,
    )


def _org_response(org: Organization, role: OrgRole) -> OrgResponse:
    return OrgResponse(
        id=org.id,
        name=org.name,
        is_personal=org.is_personal,
        role=role.value,
        created_at=org.created_at,
    )


def _member_response(member: OrganizationMember, user: User) -> MemberResponse:
    return MemberResponse(
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=member.role.value,
        created_at=member.created_at,
    )


def _invite_response(invite: OrganizationInvite) -> InviteResponse:
    return InviteResponse(
        id=invite.id,
        email=invite.email,
        role=invite.role.value,
        expires_at=invite.expires_at,
        accepted_at=invite.accepted_at,
        created_at=invite.created_at,
    )


# --- organizations ----------------------------------------------------------


@router.post("/orgs", status_code=201, response_model=OrgResponse)
async def create_org(
    body: OrgCreate,
    current_user: CurrentUser,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OrgResponse:
    org = await _service(request, session).create_org(body.name, current_user)
    await session.refresh(org)  # server-default created_at
    return _org_response(org, OrgRole.OWNER)


@router.get("/orgs", response_model=OrgListResponse)
async def list_orgs(
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OrgListResponse:
    """The orgs the caller belongs to, with their role in each."""
    pairs = await OrganizationRepository(session).list_orgs_for_user(current_user.id)
    items = [_org_response(org, role) for org, role in pairs]
    return OrgListResponse(items=items, total=len(items))


@router.get("/orgs/{org_id}", response_model=OrgResponse)
async def get_org(
    org_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OrgResponse:
    membership = await authorize_org(session, org_id, current_user, Permission.VIEW)
    org = await OrganizationRepository(session).get(org_id)
    assert org is not None  # membership implies the org exists
    return _org_response(org, membership.role)


@router.delete("/orgs/{org_id}", status_code=204)
async def delete_org(
    org_id: uuid.UUID,
    current_user: CurrentUser,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Delete a team (owner only). Personal orgs cannot be deleted (ADR-0032)."""
    await authorize_org(session, org_id, current_user, Permission.MANAGE_ORG)
    org = await OrganizationRepository(session).get(org_id)
    assert org is not None
    try:
        await _service(request, session).delete_org(org)
    except CannotDeletePersonalOrgError:
        raise HTTPException(
            status_code=400, detail="cannot delete a personal organization"
        ) from None
    return Response(status_code=204)


# --- members ----------------------------------------------------------------


@router.get("/orgs/{org_id}/members", response_model=MemberListResponse)
async def list_members(
    org_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MemberListResponse:
    """The org's members (any member may view the roster)."""
    await authorize_org(session, org_id, current_user, Permission.VIEW)
    rows = await OrganizationRepository(session).list_members(org_id)
    items = [_member_response(member, user) for member, user in rows]
    return MemberListResponse(items=items, total=len(items))


@router.patch("/orgs/{org_id}/members/{user_id}", response_model=MemberResponse)
async def change_member_role(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    body: RoleUpdate,
    current_user: CurrentUser,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MemberResponse:
    actor = await authorize_org(
        session, org_id, current_user, Permission.MANAGE_MEMBERS
    )
    try:
        member = await _service(request, session).change_role(
            org_id=org_id,
            actor=actor,
            target_user_id=user_id,
            new_role=OrgRole(body.role),
        )
    except MemberNotFoundError:
        raise HTTPException(status_code=404, detail="member not found") from None
    except RoleManagementError:
        raise HTTPException(
            status_code=403, detail="only an owner may manage owners"
        ) from None
    except LastOwnerError:
        raise HTTPException(
            status_code=409, detail="an organization must keep at least one owner"
        ) from None
    user = await session.get(User, user_id)
    assert user is not None
    return _member_response(member, user)


@router.delete("/orgs/{org_id}/members/{user_id}", status_code=204)
async def remove_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: CurrentUser,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    actor = await authorize_org(
        session, org_id, current_user, Permission.MANAGE_MEMBERS
    )
    try:
        await _service(request, session).remove_member(
            org_id=org_id, actor=actor, target_user_id=user_id
        )
    except MemberNotFoundError:
        raise HTTPException(status_code=404, detail="member not found") from None
    except RoleManagementError:
        raise HTTPException(
            status_code=403, detail="only an owner may manage owners"
        ) from None
    except LastOwnerError:
        raise HTTPException(
            status_code=409, detail="an organization must keep at least one owner"
        ) from None
    return Response(status_code=204)


# --- invites ----------------------------------------------------------------


@router.post("/orgs/{org_id}/invites", status_code=201, response_model=InviteResponse)
async def create_invite(
    org_id: uuid.UUID,
    body: InviteCreate,
    current_user: CurrentUser,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InviteResponse:
    actor = await authorize_org(
        session, org_id, current_user, Permission.MANAGE_MEMBERS
    )
    org = await OrganizationRepository(session).get(org_id)
    assert org is not None
    try:
        invite = await _service(request, session).invite(
            org=org,
            actor_role=actor.role,
            email=body.email,
            role=OrgRole(body.role),
            invited_by=current_user.id,
        )
    except RoleManagementError:
        raise HTTPException(
            status_code=403, detail="only an owner may invite an owner"
        ) from None
    except AlreadyMemberError:
        raise HTTPException(
            status_code=409, detail="that person is already a member"
        ) from None
    return _invite_response(invite)


@router.get("/orgs/{org_id}/invites", response_model=InviteListResponse)
async def list_invites(
    org_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InviteListResponse:
    await authorize_org(session, org_id, current_user, Permission.MANAGE_MEMBERS)
    invites = await OrganizationInviteRepository(session).list_pending(org_id)
    items = [_invite_response(invite) for invite in invites]
    return InviteListResponse(items=items, total=len(items))


@router.post("/invites/accept", response_model=InviteAcceptResponse)
async def accept_invite(
    body: InviteAccept,
    current_user: CurrentUser,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InviteAcceptResponse:
    """Join the inviting org as the authenticated user (token = authorization)."""
    try:
        member = await _service(request, session).accept_invite(
            body.token, current_user
        )
    except InvalidInviteError:
        raise HTTPException(
            status_code=400, detail="invalid or expired invite"
        ) from None
    return InviteAcceptResponse(
        org_id=member.org_id,
        role=member.role.value,
    )
