"""AuthStrategy contract + value objects (T4.2a).

A single pluggable seam for getting a logged-in browser session against a live
target, mirroring the other provider contracts (AIProvider / EmbeddingProvider /
GitProvider): one abstract ``AuthStrategy`` with a config-driven registry, a
no-auth and a stub implementation, the interim manual-OTP implementation, and
declared-but-parked automated variants behind the same contract.

OTP/2FA is CONFIGURED, never cracked: the manual strategy obtains the code from
an injected ``OtpProvider`` (an interactive prompt in real use; a canned value in
tests) — the tester reads it off their own device. Browser driving is abstracted
behind ``LoginBrowser`` so the strategy logic is testable without a real browser.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AuthChallenge, AuthVariant


@dataclass(frozen=True)
class AuthConfig:
    """Per-target login configuration for a strategy.

    ``account`` is the tester's registered identifier (phone/email) — used to
    prompt them and as the session cache key; it is redacted before logging and
    never persisted in full. Selectors have sensible cross-stack defaults.
    """

    login_url: str
    username: str
    # The target secret. Excluded from the dataclass repr so it can't leak through an
    # f-string, a traceback, or a log line (the same defence as ResolvedTargetLogin).
    password: str = field(repr=False)
    account: str
    username_selector: str = (
        "input[type=email], input[name=email], input[name=username]"
    )
    password_selector: str = "input[type=password], input[name=password]"
    submit_selector: str = "button[type=submit], input[type=submit]"
    otp_selector: str = (
        "input[name=otp], input[name=code], input[autocomplete=one-time-code]"
    )
    otp_submit_selector: str = "button[type=submit], input[type=submit]"
    success_selector: str | None = None


@dataclass(frozen=True)
class OtpRequest:
    """What the OtpProvider is asked for when a challenge is detected.

    Carries the full ``account`` so an interactive prompt can tell the tester
    which device to read — this object is NEVER logged or persisted.
    """

    project_id: uuid.UUID
    account: str
    channel: str | None = None


# Returns the one-time code for a challenge. Interactive in real use; injected in
# tests. Implementations must not log the code they return.
OtpProvider = Callable[[OtpRequest], str]


@dataclass(frozen=True)
class LoginOutcome:
    """What the browser layer produced for one login attempt."""

    storage_state: dict[str, Any]  # Playwright storageState (cookies + origins)
    challenge: AuthChallenge
    channel: str | None
    success: bool


@dataclass(frozen=True)
class AuthSession:
    """A reusable logged-in session: a browser storageState + metadata.

    ``storage_state`` is replayed into fresh browser contexts (e.g. by the
    crawler) so the tester logs in — and enters OTP — at most once per run.
    """

    variant: AuthVariant
    storage_state: dict[str, Any] | None
    account: str | None
    challenge: AuthChallenge
    created_at: datetime
    expires_at: datetime | None

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at


@runtime_checkable
class LoginBrowser(Protocol):
    """Drives the actual browser login. Real impl uses Playwright; tests fake it.

    The browser owns the DOM flow and calls ``otp_provider`` itself when it
    detects a challenge, so the strategy stays browser-agnostic.
    """

    def run_login(
        self,
        config: AuthConfig,
        otp_provider: OtpProvider,
        request: OtpRequest,
    ) -> LoginOutcome: ...


class AuthStrategy(ABC):
    """Pluggable login seam: produce a reusable AuthSession for a target."""

    variant: AuthVariant

    @abstractmethod
    async def login(
        self,
        *,
        session: AsyncSession,
        project_id: uuid.UUID,
        config: AuthConfig | None,
    ) -> AuthSession:
        """Return a logged-in session (reused until expiry where applicable)."""
        ...
