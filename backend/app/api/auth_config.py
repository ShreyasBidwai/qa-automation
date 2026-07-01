"""Login-config routes (ADR-0056) — set / view / clear a project's ``auth_config``.

The authenticated crawl needs to know WHERE to log in (a ``login_url`` + optional DOM
selectors); these live in ``project.settings['auth_config']`` and are what
``resolve_target_auth_config`` reads. This carries NO secret — the account, password,
and TOTP seed are in the encrypted vault (ADR-0053); mutations are MANAGE_PROJECT.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.models.project import Project
from app.repositories.project_repository import ProjectRepository

from .authz import authorize_project
from .deps import CurrentUser, get_session
from .schemas import AuthConfigResponse, AuthConfigUpsert

router = APIRouter(prefix="/api/v1", tags=["auth-config"])

_AUTH_CONFIG_KEY = "auth_config"
_SELECTOR_FIELDS = (
    "username_selector",
    "password_selector",
    "submit_selector",
    "otp_selector",
    "otp_submit_selector",
    "success_selector",
)


def _response(cfg: Any) -> AuthConfigResponse:
    """The stored config → the safe response; unconfigured when there's no login_url."""
    if not isinstance(cfg, dict) or not cfg.get("login_url"):
        return AuthConfigResponse(configured=False)
    return AuthConfigResponse(
        configured=True,
        login_url=cfg.get("login_url"),
        **{key: cfg.get(key) for key in _SELECTOR_FIELDS},
    )


async def _project(
    session: AsyncSession,
    project_id: uuid.UUID,
    user: CurrentUser,
    permission: Permission,
) -> Project:
    await authorize_project(session, project_id, user, permission)
    project = await ProjectRepository(session).get(project_id)
    if project is None:  # pragma: no cover — authorize_project already 404s the miss
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.get("/projects/{project_id}/auth-config", response_model=AuthConfigResponse)
async def get_auth_config(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthConfigResponse:
    """A project's login config, or ``configured=false`` (VIEW). No secret."""
    project = await _project(session, project_id, current_user, Permission.VIEW)
    return _response((project.settings or {}).get(_AUTH_CONFIG_KEY))


@router.put("/projects/{project_id}/auth-config", response_model=AuthConfigResponse)
async def set_auth_config(
    project_id: uuid.UUID,
    body: AuthConfigUpsert,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthConfigResponse:
    """Set/replace the login config so runs can crawl behind the gate (MANAGE_PROJECT).

    Only ``login_url`` + non-empty selector overrides are stored; the AuthConfig
    defaults cover the rest. No secret is accepted here (those go to the vault).
    """
    project = await _project(
        session, project_id, current_user, Permission.MANAGE_PROJECT
    )
    cfg: dict[str, str] = {"login_url": body.login_url.strip()}
    for field in _SELECTOR_FIELDS:
        value = getattr(body, field)
        if value and value.strip():
            cfg[field] = value.strip()
    settings = dict(project.settings or {})
    settings[_AUTH_CONFIG_KEY] = cfg
    project.settings = settings  # reassign so the JSONB change is tracked
    await session.flush()
    return _response(cfg)


@router.delete("/projects/{project_id}/auth-config", status_code=204)
async def clear_auth_config(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Clear the login config (the crawl reverts to unauthenticated). 404 if unset."""
    project = await _project(
        session, project_id, current_user, Permission.MANAGE_PROJECT
    )
    settings = dict(project.settings or {})
    if _AUTH_CONFIG_KEY not in settings:
        raise HTTPException(status_code=404, detail="no login config to clear")
    del settings[_AUTH_CONFIG_KEY]
    project.settings = settings
    await session.flush()
    return Response(status_code=204)
