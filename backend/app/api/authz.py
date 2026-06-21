"""RBAC enforcement at the API boundary (B3, ADR-0033).

One code path every data endpoint funnels through. The 404/403 split is the whole
point and is enforced here, in one place:

  - resource missing, or caller is **not a member** of its org → ``404``
    (existence is not leaked to outsiders);
  - caller **is** a member but the role lacks the permission → ``403``
    (they can already see it exists; hiding it buys nothing).
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission, role_can
from app.models.organization_member import OrganizationMember
from app.models.project import Project
from app.models.user import User
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository


async def authorize_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    user: User,
    permission: Permission,
) -> Project:
    """Return the project iff ``user`` may perform ``permission`` on it.

    404 if the project is missing/deleted or the user is not in its org; 403 if
    they are in the org but their role does not permit the action (ADR-0033).
    """
    project = await ProjectRepository(session).get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    membership = await OrganizationRepository(session).get_membership(
        project.org_id, user.id
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="project not found")
    if not role_can(membership.role, permission):
        raise HTTPException(status_code=403, detail="insufficient permissions")
    return project


async def authorize_org(
    session: AsyncSession,
    org_id: uuid.UUID,
    user: User,
    permission: Permission,
) -> OrganizationMember:
    """Return the caller's membership iff their role permits ``permission``.

    404 if the user is not a member of the org (leak-safe); 403 if they are but the
    role is insufficient (ADR-0033).
    """
    membership = await OrganizationRepository(session).get_membership(org_id, user.id)
    if membership is None:
        raise HTTPException(status_code=404, detail="organization not found")
    if not role_can(membership.role, permission):
        raise HTTPException(status_code=403, detail="insufficient permissions")
    return membership
