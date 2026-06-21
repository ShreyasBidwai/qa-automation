"""AuthService — email/password auth business logic (B2, ADR-0030).

Orchestrates the user/session/reset repositories + the security primitives + the
mailer. The API router is thin; all rules live here so they unit-test directly.
Sessions are server-side opaque bearer tokens (real revocation on sign-out);
reset tokens are single-use and short-lived. No secret is ever logged.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.models.user_session import UserSession
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.password_reset_token_repository import (
    PasswordResetTokenRepository,
)
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.services.errors import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidResetTokenError,
)
from app.services.mailer import Mailer


def normalize_email(email: str) -> str:
    return email.strip().lower()


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        mailer: Mailer,
        session_ttl_seconds: int,
        reset_ttl_seconds: int,
    ) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._sessions = SessionRepository(session)
        self._resets = PasswordResetTokenRepository(session)
        self._orgs = OrganizationRepository(session)
        self._mailer = mailer
        self._session_ttl = session_ttl_seconds
        self._reset_ttl = reset_ttl_seconds

    async def sign_up(self, email: str, password: str) -> tuple[User, str]:
        """Create a user, their personal org, and an initial session (ADR-0032).

        Every user gets a personal organization they own, so a solo user keeps
        working with no "make a team first" step. Raises if the email is taken.
        """
        email = normalize_email(email)
        if await self._users.get_by_email(email) is not None:
            raise EmailAlreadyRegisteredError(email)
        user = await self._users.add(
            User(email=email, password_hash=hash_password(password))
        )
        org = await self._orgs.add(
            Organization(name=email.split("@", 1)[0] or "personal", is_personal=True)
        )
        await self._orgs.add_member(org.id, user.id, OrgRole.OWNER)
        return user, await self._issue_session(user.id)

    async def update_profile(self, user: User, changes: dict[str, str | None]) -> User:
        """Update the account profile (B3): display name and/or email.

        Only keys present in ``changes`` are touched. ``name`` may be set to None to
        clear it; an ``email`` change is checked for uniqueness (→ 409 at the
        boundary). The email is already normalized by the request schema.
        """
        if "email" in changes and changes["email"]:
            new_email = normalize_email(changes["email"])
            if new_email != user.email:
                if await self._users.get_by_email(new_email) is not None:
                    raise EmailAlreadyRegisteredError(new_email)
                user.email = new_email
        if "name" in changes:
            user.name = changes["name"]
        await self._session.flush()
        return user

    async def change_password(
        self,
        user: User,
        *,
        current_password: str,
        new_password: str,
        current_token: str,
    ) -> None:
        """Change the password after re-verifying the current one (B3).

        Wrong current password → ``InvalidCredentialsError``. On success every other
        session is revoked (the current device stays signed in); a stolen old token
        elsewhere dies, mirroring the reset flow's revocation (ADR-0030).
        """
        if not verify_password(user.password_hash, current_password):
            raise InvalidCredentialsError
        user.password_hash = hash_password(new_password)
        await self._sessions.delete_for_user_except(user.id, hash_token(current_token))
        await self._session.flush()

    async def sign_in(self, email: str, password: str) -> tuple[User, str]:
        """Verify credentials and issue a session. Raises on any mismatch."""
        user = await self._users.get_by_email(normalize_email(email))
        if user is None or not user.is_active:
            raise InvalidCredentialsError
        if not verify_password(user.password_hash, password):
            raise InvalidCredentialsError
        return user, await self._issue_session(user.id)

    async def sign_out(self, token: str) -> None:
        """Revoke the bearer token's session (idempotent)."""
        await self._sessions.delete_by_token_hash(hash_token(token))

    async def request_password_reset(self, email: str) -> None:
        """Issue + 'email' a reset token. Silent for unknown emails (no enum)."""
        user = await self._users.get_by_email(normalize_email(email))
        if user is None:
            return  # do not reveal whether the account exists
        token = generate_token()
        await self._resets.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(token),
                expires_at=self._now() + timedelta(seconds=self._reset_ttl),
            )
        )
        await self._mailer.send_password_reset(email=user.email, token=token)

    async def reset_password(self, token: str, new_password: str) -> None:
        """Consume a reset token, set the new password, revoke all sessions.

        Rejects an unknown / used / expired token uniformly (InvalidResetTokenError).
        """
        record = await self._resets.get_by_token_hash(hash_token(token))
        if record is None or record.used_at is not None:
            raise InvalidResetTokenError
        if record.expires_at <= self._now():
            raise InvalidResetTokenError
        user = await self._users.get(record.user_id)
        if user is None:
            raise InvalidResetTokenError
        user.password_hash = hash_password(new_password)
        record.used_at = self._now()  # single-use
        await self._sessions.delete_for_user(user.id)  # force re-login
        await self._session.flush()

    async def _issue_session(self, user_id: uuid.UUID) -> str:
        token = generate_token()
        await self._sessions.add(
            UserSession(
                user_id=user_id,
                token_hash=hash_token(token),
                expires_at=self._now() + timedelta(seconds=self._session_ttl),
            )
        )
        return token

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)
