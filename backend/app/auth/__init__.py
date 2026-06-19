"""Pluggable authentication seam (T4.2a, Architecture §7/§9).

One ``AuthStrategy`` contract (mirroring AIProvider / EmbeddingProvider /
GitProvider) for getting a reusable logged-in browser session against a live
target. Ships the no-auth, stub, and interim manual-OTP strategies; automated
variants are declared but parked (docs/parking-lot.md). OTP/2FA is configured,
never cracked; secrets are never logged.
"""

from __future__ import annotations

from .browser import PlaywrightLoginBrowser
from .errors import AuthConfigError, AuthError, LoginFailedError
from .factory import build_auth_strategy
from .otp import prompt_for_otp
from .redact import redact_label
from .strategy import (
    EmailOtpStrategy,
    ManualOtpStrategy,
    NoAuthStrategy,
    SmsOtpStrategy,
    StubAuthStrategy,
    TotpStrategy,
)
from .types import (
    AuthConfig,
    AuthSession,
    AuthStrategy,
    LoginBrowser,
    LoginOutcome,
    OtpProvider,
    OtpRequest,
)

__all__ = [
    "AuthConfig",
    "AuthConfigError",
    "AuthError",
    "AuthSession",
    "AuthStrategy",
    "EmailOtpStrategy",
    "LoginBrowser",
    "LoginFailedError",
    "LoginOutcome",
    "ManualOtpStrategy",
    "NoAuthStrategy",
    "OtpProvider",
    "OtpRequest",
    "PlaywrightLoginBrowser",
    "SmsOtpStrategy",
    "StubAuthStrategy",
    "TotpStrategy",
    "build_auth_strategy",
    "prompt_for_otp",
    "redact_label",
]
