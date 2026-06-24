"""Decrypt-at-use accessor — the ONLY place a target secret is decrypted (ADR-0053).

A run calls ``resolve_target_login`` when it needs to authenticate as a project's
specific target account. The secret is decrypted into memory here and returned inside
``ResolvedTargetLogin``; it is never persisted decrypted and never passed through a
layer that logs. ``ResolvedTargetLogin`` overrides ``repr``/``str`` so the secret can
never leak through an f-string, a traceback, an incident capture, or a log line.

Anything other than this module reading a target secret in the clear is a bug.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.redact import redact_label
from app.models.enums import CredentialMode
from app.repositories.target_credentials_repository import TargetCredentialsRepository

from .crypto import decrypt_secret


@dataclass(frozen=True)
class ResolvedTargetLogin:
    """A decrypted, in-memory target login. NEVER log or persist this.

    ``secret`` is plaintext and is deliberately excluded from ``repr``/``str`` — the
    only safe rendering is the redacted identifier.
    """

    identifier: str
    secret: str = field(repr=False)  # excluded from the dataclass repr (defense)

    def __repr__(self) -> str:  # belt and braces over field(repr=False)
        label = redact_label(self.identifier)
        return f"ResolvedTargetLogin(identifier={label!r}, secret=***)"

    __str__ = __repr__


async def resolve_target_login(
    session: AsyncSession, project_id: uuid.UUID
) -> ResolvedTargetLogin | None:
    """The target login a run should authenticate with, or None to self-provision.

    Returns ``None`` (Polaris provisions its own account — existing behaviour) when
    there are no credentials, the mode is ``polaris_creates``, or a specific-account
    record is incomplete. For a complete ``specific_account`` record this is the one
    place the stored secret is decrypted (in memory, at the point of use).
    """
    record = await TargetCredentialsRepository(session).get(project_id)
    if (
        record is None
        or record.mode != CredentialMode.SPECIFIC_ACCOUNT.value
        or record.identifier is None
        or record.encrypted_secret is None
    ):
        return None
    return ResolvedTargetLogin(
        identifier=record.identifier,
        secret=decrypt_secret(record.encrypted_secret),
    )
