"""Target-account credentials routes (ADR-0053) — set / view / clear.

The account secret is WRITE-ONLY: ``PUT`` encrypts it before it touches the DB, and
neither ``GET`` nor any other payload ever returns or decrypts it. All three routes
are gated on MANAGE_PROJECT — the credential identifier is account PII and configuring
it is a project-management action. The secret is never logged here.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.credentials import CredentialsKeyError, encrypt_secret
from app.models.enums import CredentialMode
from app.models.target_credentials import TargetCredentials
from app.repositories.target_credentials_repository import TargetCredentialsRepository

from .authz import authorize_project
from .deps import CurrentUser, get_session
from .schemas import CredentialStatusResponse, CredentialUpsert

router = APIRouter(prefix="/api/v1", tags=["credentials"])


def _status(record: TargetCredentials) -> CredentialStatusResponse:
    # has_credentials / has_totp = whether the encrypted values are stored; NEITHER
    # secret is ever included — the response model has no field for them (defence).
    return CredentialStatusResponse(
        mode=record.mode,
        identifier=record.identifier,
        has_credentials=record.encrypted_secret is not None,
        has_totp=record.encrypted_totp_secret is not None,
    )


@router.put(
    "/projects/{project_id}/credentials", response_model=CredentialStatusResponse
)
async def set_credentials(
    project_id: uuid.UUID,
    body: CredentialUpsert,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CredentialStatusResponse:
    """Set/replace a project's target credentials (MANAGE_PROJECT).

    For ``specific_account`` the secret is encrypted before storage; if no encryption
    key is configured the write REFUSES (503) and nothing is stored — plaintext is
    never persisted. ``polaris_creates`` clears any stored account/secret.
    """
    await authorize_project(
        session, project_id, current_user, Permission.MANAGE_PROJECT
    )

    repo = TargetCredentialsRepository(session)
    identifier: str | None = None
    encrypted: bytes | None = None
    encrypted_totp: bytes | None = None
    if body.mode == CredentialMode.SPECIFIC_ACCOUNT.value:
        identifier = body.identifier.strip() if body.identifier else None
        try:
            # ``secret`` is guaranteed present for specific_account by the schema.
            encrypted = encrypt_secret(body.secret.get_secret_value())  # type: ignore[union-attr]
            if body.totp_secret is not None:
                encrypted_totp = encrypt_secret(body.totp_secret.get_secret_value())
            else:
                # Omitted ⇒ preserve any stored TOTP seed (don't wipe it on a
                # password-only update); only polaris_creates clears it.
                existing = await repo.get(project_id)
                encrypted_totp = existing.encrypted_totp_secret if existing else None
        except CredentialsKeyError:
            raise HTTPException(
                status_code=503, detail="credential encryption is not configured"
            ) from None

    record = await repo.upsert(
        project_id,
        mode=body.mode,
        identifier=identifier,
        encrypted_secret=encrypted,
        encrypted_totp_secret=encrypted_totp,
    )
    return _status(record)


@router.get(
    "/projects/{project_id}/credentials", response_model=CredentialStatusResponse
)
async def get_credentials(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CredentialStatusResponse:
    """The safe credential status — mode + identifier + has_credentials, NEVER the
    secret (MANAGE_PROJECT). An unconfigured project reads as ``polaris_creates``."""
    await authorize_project(
        session, project_id, current_user, Permission.MANAGE_PROJECT
    )
    record = await TargetCredentialsRepository(session).get(project_id)
    if record is None:
        return CredentialStatusResponse(
            mode=CredentialMode.POLARIS_CREATES.value,
            identifier=None,
            has_credentials=False,
        )
    return _status(record)


@router.delete("/projects/{project_id}/credentials", status_code=204)
async def clear_credentials(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Clear a project's stored credentials (MANAGE_PROJECT). 404 if there are none."""
    await authorize_project(
        session, project_id, current_user, Permission.MANAGE_PROJECT
    )
    if not await TargetCredentialsRepository(session).delete(project_id):
        raise HTTPException(status_code=404, detail="no credentials to clear")
    return Response(status_code=204)
