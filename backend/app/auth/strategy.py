"""AuthStrategy implementations (T4.2a).

Implemented now: ``NoAuthStrategy`` (no login), ``StubAuthStrategy`` (tests), and
``ManualOtpStrategy`` (the interim one — drives login in a browser, gets the OTP
from an injected provider, caches/reuses the session). The automated variants
(``totp`` / ``email_otp`` / ``sms_otp``) are declared behind the same contract
but parked: their ``login`` raises ``NotImplementedError`` pointing at
docs/parking-lot.md. OTP/2FA is configured, never cracked.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_challenge_log import AuthChallengeLog
from app.models.enums import AuthChallenge, AuthVariant
from app.repositories.auth_challenge_log_repository import AuthChallengeLogRepository

from .errors import AuthConfigError, LoginFailedError
from .redact import redact_label
from .types import (
    AuthConfig,
    AuthSession,
    AuthStrategy,
    LoginBrowser,
    OtpProvider,
    OtpRequest,
)

logger = logging.getLogger("app.auth")

Clock = Callable[[], datetime]
_PARKED = "auto-auth is parked — see docs/parking-lot.md"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class NoAuthStrategy(AuthStrategy):
    """No login — an empty session (the crawler/runner use a fresh context)."""

    variant = AuthVariant.NONE

    def __init__(self, *, clock: Clock = _utcnow) -> None:
        self._clock = clock

    async def login(
        self,
        *,
        session: AsyncSession,
        project_id: uuid.UUID,
        config: AuthConfig | None,
    ) -> AuthSession:
        now = self._clock()
        return AuthSession(
            variant=self.variant,
            storage_state=None,
            account=None,
            challenge=AuthChallenge.NONE,
            created_at=now,
            expires_at=None,
        )


class StubAuthStrategy(AuthStrategy):
    """A canned, already-logged-in session for tests — no browser, no prompt."""

    variant = AuthVariant.TEST_BYPASS

    def __init__(
        self,
        *,
        storage_state: dict[str, Any] | None = None,
        clock: Clock = _utcnow,
    ) -> None:
        self._storage_state: dict[str, Any] = (
            storage_state if storage_state is not None else {}
        )
        self._clock = clock

    async def login(
        self,
        *,
        session: AsyncSession,
        project_id: uuid.UUID,
        config: AuthConfig | None,
    ) -> AuthSession:
        now = self._clock()
        return AuthSession(
            variant=self.variant,
            storage_state=dict(self._storage_state),
            account=config.account if config else None,
            challenge=AuthChallenge.NONE,
            created_at=now,
            expires_at=None,
        )


class ManualOtpStrategy(AuthStrategy):
    """Interim manual OTP/2FA: drive login, get the code from the tester, reuse.

    The browser drives username/password, detects the challenge, and calls the
    injected ``OtpProvider`` for the code; the resulting session is cached by
    ``(project_id, account)`` and reused until expiry, so the tester enters OTP
    at most once per run. Every *attempt* (cache miss) appends a redacted record
    to the challenge log; secrets are never logged or persisted.
    """

    variant = AuthVariant.MANUAL

    def __init__(
        self,
        *,
        browser: LoginBrowser,
        otp_provider: OtpProvider,
        clock: Clock = _utcnow,
        session_ttl_s: float = 3600.0,
    ) -> None:
        self._browser = browser
        self._otp_provider = otp_provider
        self._clock = clock
        self._ttl = session_ttl_s
        self._cache: dict[tuple[uuid.UUID, str], AuthSession] = {}

    async def login(
        self,
        *,
        session: AsyncSession,
        project_id: uuid.UUID,
        config: AuthConfig | None,
    ) -> AuthSession:
        if config is None:
            raise AuthConfigError("manual auth requires an AuthConfig")

        now = self._clock()
        key = (project_id, config.account)
        cached = self._cache.get(key)
        if cached is not None and not cached.is_expired(now):
            return cached  # reuse — no second browser drive, no second OTP prompt

        request = OtpRequest(project_id=project_id, account=config.account)
        outcome = self._browser.run_login(config, self._otp_provider, request)

        # Record the encounter (redacted) BEFORE raising on failure, so failures
        # are still captured for analysis. Never log the code/password/number.
        await AuthChallengeLogRepository(session).append(
            AuthChallengeLog(
                project_id=project_id,
                target_url=config.login_url,
                challenge=outcome.challenge,
                channel=outcome.channel,
                account_label=redact_label(config.account),
                outcome="success" if outcome.success else "failure",
            )
        )
        logger.info(
            "auth.login_attempt",
            extra={
                "project_id": str(project_id),
                "challenge": outcome.challenge.value,
                "channel": outcome.channel,
                "outcome": "success" if outcome.success else "failure",
            },
        )
        if not outcome.success:
            raise LoginFailedError(
                f"login did not succeed for {redact_label(config.account)}"
            )

        auth_session = AuthSession(
            variant=self.variant,
            storage_state=outcome.storage_state,
            account=config.account,
            challenge=outcome.challenge,
            created_at=now,
            expires_at=now + timedelta(seconds=self._ttl),
        )
        self._cache[key] = auth_session
        return auth_session


class _ParkedStrategy(AuthStrategy):
    """Declared-but-unimplemented automated variant (same contract)."""

    async def login(
        self,
        *,
        session: AsyncSession,
        project_id: uuid.UUID,
        config: AuthConfig | None,
    ) -> AuthSession:
        raise NotImplementedError(f"{self.variant.value} {_PARKED}")


class TotpStrategy(_ParkedStrategy):
    """Automated TOTP (e.g. pyotp) — parked (docs/parking-lot.md)."""

    variant = AuthVariant.TOTP


class EmailOtpStrategy(_ParkedStrategy):
    """Automated email OTP via a test inbox — parked (docs/parking-lot.md)."""

    variant = AuthVariant.EMAIL_OTP


class SmsOtpStrategy(_ParkedStrategy):
    """Automated SMS OTP via a number provider — parked (docs/parking-lot.md)."""

    variant = AuthVariant.SMS_OTP
