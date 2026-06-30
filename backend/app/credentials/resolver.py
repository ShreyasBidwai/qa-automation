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
from app.auth.types import AuthConfig
from app.models.enums import CredentialMode
from app.repositories.project_repository import ProjectRepository
from app.repositories.target_credentials_repository import TargetCredentialsRepository

from .crypto import decrypt_secret

# The optional per-target login config the operator sets on a project so a run can
# log in and crawl behind the gate (ADR-0056). Lives under
# ``project.settings['auth_config']`` (additive, no schema change): a ``login_url``
# plus optional DOM selector overrides
# (the defaults on AuthConfig cover most stacks). Absent ⇒ the crawl stays
# unauthenticated (Polaris-self-provision path). The username/password come from the
# encrypted credentials vault, never from settings.
_AUTH_CONFIG_KEY = "auth_config"
_SELECTOR_KEYS = (
    "username_selector",
    "password_selector",
    "submit_selector",
    "otp_selector",
    "otp_submit_selector",
    "success_selector",
)


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


async def resolve_target_auth_config(
    session: AsyncSession, project_id: uuid.UUID
) -> AuthConfig | None:
    """The login config a run should authenticate the crawl with, or None.

    Returns None (the crawl runs unauthenticated, as before) unless BOTH are set:
    a complete ``specific_account`` credential (so we have a username + secret) AND
    a ``project.settings['auth_config']`` carrying at least a ``login_url`` (so we
    know where to log in). The secret is decrypted at use via ``resolve_target_login``
    and lives only inside the returned ``AuthConfig`` (whose repr masks it); it is
    never read from settings or logged. Selector overrides, when present, refine the
    cross-stack defaults baked into AuthConfig.
    """
    login = await resolve_target_login(session, project_id)
    if login is None:
        return None  # no specific account → Polaris self-provisions (no login)
    project = await ProjectRepository(session).get(project_id)
    raw = (project.settings or {}).get(_AUTH_CONFIG_KEY) if project else None
    if not isinstance(raw, dict):
        return None
    login_url = raw.get("login_url")
    if not isinstance(login_url, str) or not login_url:
        return None  # nowhere to log in → can't drive a login; skip authed crawl
    overrides = {
        key: raw[key]
        for key in _SELECTOR_KEYS
        if isinstance(raw.get(key), str) and raw[key]
    }
    return AuthConfig(
        login_url=login_url,
        username=login.identifier,
        password=login.secret,
        account=login.identifier,
        **overrides,
    )
