"""AuthStrategy seam — fast tests (no real browser, no interactive prompt).

A fake LoginBrowser + an injected OtpProvider exercise ManualOtpStrategy: a
session is captured and reused (OTP entered at most once), the challenge log is
written with correct, REDACTED metadata and never any secret, parked variants
raise NotImplementedError, and the registry resolves a strategy by variant.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import AuthConfigError, LoginFailedError
from app.auth.factory import build_auth_strategy
from app.auth.redact import redact_label
from app.auth.strategy import (
    ManualOtpStrategy,
    NoAuthStrategy,
    StubAuthStrategy,
    TotpStrategy,
)
from app.auth.types import AuthConfig, LoginOutcome, OtpProvider, OtpRequest
from app.models.enums import AuthChallenge, AuthVariant
from app.repositories.auth_challenge_log_repository import AuthChallengeLogRepository
from tests.factories import make_project

_FIXED = datetime(2026, 1, 1, tzinfo=UTC)


class _FakeBrowser:
    """Simulates a browser login: optionally raises a challenge → calls otp."""

    def __init__(
        self,
        *,
        storage_state: dict[str, Any],
        challenge: AuthChallenge = AuthChallenge.OTP,
        channel: str | None = "sms",
        success: bool = True,
    ) -> None:
        self.calls = 0
        self._storage_state = storage_state
        self._challenge = challenge
        self._channel = channel
        self._success = success

    def run_login(
        self, config: AuthConfig, otp_provider: OtpProvider, request: OtpRequest
    ) -> LoginOutcome:
        self.calls += 1
        if self._challenge is not AuthChallenge.NONE:
            otp_provider(request)  # the tester supplies the code
        return LoginOutcome(
            storage_state=self._storage_state,
            challenge=self._challenge,
            channel=self._channel,
            success=self._success,
        )


class _OtpStub:
    def __init__(self, code: str = "123456") -> None:
        self.code = code
        self.calls = 0

    def __call__(self, request: OtpRequest) -> str:
        self.calls += 1
        return self.code


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


def _config(**overrides: Any) -> AuthConfig:
    base: dict[str, Any] = dict(
        login_url="https://target.test/login",
        username="user@example.com",
        password="hunter2",
        account="jane@example.com",
    )
    base.update(overrides)
    return AuthConfig(**base)


# --- manual OTP: capture + reuse --------------------------------------------


async def test_manual_otp_captures_and_reuses_session(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    browser = _FakeBrowser(storage_state={"cookies": [{"name": "s", "value": "v"}]})
    otp = _OtpStub("654321")
    strat = ManualOtpStrategy(browser=browser, otp_provider=otp, clock=lambda: _FIXED)
    config = _config()

    first = await strat.login(session=db_session, project_id=project_id, config=config)
    assert first.variant is AuthVariant.MANUAL
    assert first.storage_state == {"cookies": [{"name": "s", "value": "v"}]}
    assert browser.calls == 1 and otp.calls == 1

    # Second call (same project+account) reuses — no second browser drive/OTP.
    second = await strat.login(session=db_session, project_id=project_id, config=config)
    assert second.storage_state == first.storage_state
    assert browser.calls == 1 and otp.calls == 1

    # Exactly one challenge-log row (the reuse is not a fresh attempt).
    rows = await AuthChallengeLogRepository(db_session).list_for_project(project_id)
    assert len(rows) == 1


# --- challenge log: metadata + no secrets -----------------------------------


async def test_challenge_log_has_metadata_and_no_secrets(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    browser = _FakeBrowser(storage_state={}, challenge=AuthChallenge.OTP, channel="sms")
    strat = ManualOtpStrategy(browser=browser, otp_provider=_OtpStub("999111"))
    config = _config(account="+14155551234", password="hunter2")

    await strat.login(session=db_session, project_id=project_id, config=config)

    rows = await AuthChallengeLogRepository(db_session).list_for_project(project_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.target_url == "https://target.test/login"
    assert row.challenge is AuthChallenge.OTP
    assert row.channel == "sms"
    assert row.outcome == "success"
    assert row.account_label is not None and row.account_label != "+14155551234"

    blob = "|".join(
        str(v) for v in (row.target_url, row.account_label, row.channel, row.outcome)
    )
    for secret in ("hunter2", "999111", "+14155551234"):
        assert secret not in blob


async def test_login_failure_is_logged_then_raised(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    browser = _FakeBrowser(storage_state={}, success=False)
    strat = ManualOtpStrategy(browser=browser, otp_provider=_OtpStub())

    with pytest.raises(LoginFailedError):
        await strat.login(session=db_session, project_id=project_id, config=_config())

    rows = await AuthChallengeLogRepository(db_session).list_for_project(project_id)
    assert len(rows) == 1 and rows[0].outcome == "failure"


async def test_manual_requires_config(db_session: AsyncSession) -> None:
    strat = ManualOtpStrategy(
        browser=_FakeBrowser(storage_state={}), otp_provider=_OtpStub()
    )
    with pytest.raises(AuthConfigError):
        await strat.login(session=db_session, project_id=uuid.uuid4(), config=None)


# --- no-auth, registry, parked variants, redaction --------------------------


async def test_noauth_returns_empty_session(db_session: AsyncSession) -> None:
    strat = NoAuthStrategy()
    out = await strat.login(session=db_session, project_id=uuid.uuid4(), config=None)
    assert out.variant is AuthVariant.NONE
    assert out.storage_state is None
    assert out.challenge is AuthChallenge.NONE


def test_registry_resolves_strategy_by_variant() -> None:
    assert isinstance(build_auth_strategy(AuthVariant.NONE), NoAuthStrategy)
    assert isinstance(build_auth_strategy(AuthVariant.TEST_BYPASS), StubAuthStrategy)
    manual = build_auth_strategy(
        AuthVariant.MANUAL,
        browser=_FakeBrowser(storage_state={}),
        otp_provider=_OtpStub(),
    )
    assert isinstance(manual, ManualOtpStrategy)
    assert isinstance(build_auth_strategy(AuthVariant.TOTP), TotpStrategy)
    # Manual without its deps is a config error.
    with pytest.raises(AuthConfigError):
        build_auth_strategy(AuthVariant.MANUAL)


async def test_parked_variants_raise_not_implemented(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    for variant in (AuthVariant.TOTP, AuthVariant.EMAIL_OTP, AuthVariant.SMS_OTP):
        strat = build_auth_strategy(variant)
        with pytest.raises(NotImplementedError):
            await strat.login(session=db_session, project_id=project_id, config=None)


def test_redact_label_masks_identifiers() -> None:
    assert redact_label("jane@example.com") == "j•••@example.com"
    masked = redact_label("+14155551234")
    assert masked.endswith("34") and "4155551" not in masked
    assert "•••" in redact_label("x")
