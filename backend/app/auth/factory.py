"""Config-driven AuthStrategy selection (mirrors build_ai_provider, T4.2a).

Resolves an ``AuthVariant`` to a strategy. ``none``/``test_bypass``/``manual``/``totp``
are built ready-to-use (``totp`` computes the authenticator code via pyotp from the
target's TOTP secret); ``email_otp``/``sms_otp`` remain parked (docs/parking-lot.md).
"""

from __future__ import annotations

from typing import Any

from app.models.enums import AuthVariant

from .errors import AuthConfigError, AuthError
from .strategy import (
    Clock,
    EmailOtpStrategy,
    ManualOtpStrategy,
    NoAuthStrategy,
    SmsOtpStrategy,
    StubAuthStrategy,
    TotpStrategy,
    _utcnow,
)
from .types import AuthStrategy, LoginBrowser, OtpProvider


def build_auth_strategy(
    variant: AuthVariant,
    *,
    browser: LoginBrowser | None = None,
    otp_provider: OtpProvider | None = None,
    storage_state: dict[str, Any] | None = None,
    clock: Clock = _utcnow,
    session_ttl_s: float = 3600.0,
) -> AuthStrategy:
    """Build the AuthStrategy for ``variant``.

    ``manual`` requires a ``browser`` + ``otp_provider``; ``test_bypass`` accepts
    an optional canned ``storage_state``. Raises ``AuthConfigError`` when manual
    is requested without its deps, and ``AuthError`` for an unknown variant.
    """
    if variant is AuthVariant.NONE:
        return NoAuthStrategy(clock=clock)
    if variant is AuthVariant.TEST_BYPASS:
        return StubAuthStrategy(storage_state=storage_state, clock=clock)
    if variant is AuthVariant.MANUAL:
        if browser is None or otp_provider is None:
            raise AuthConfigError("manual auth requires a browser and an otp_provider")
        return ManualOtpStrategy(
            browser=browser,
            otp_provider=otp_provider,
            clock=clock,
            session_ttl_s=session_ttl_s,
        )
    if variant is AuthVariant.TOTP:
        if browser is None:
            raise AuthConfigError("totp auth requires a browser")
        return TotpStrategy(browser=browser, clock=clock, session_ttl_s=session_ttl_s)
    if variant is AuthVariant.EMAIL_OTP:
        return EmailOtpStrategy()
    if variant is AuthVariant.SMS_OTP:
        return SmsOtpStrategy()
    raise AuthError(f"unknown auth variant {variant!r}")  # pragma: no cover


__all__ = ["build_auth_strategy"]
