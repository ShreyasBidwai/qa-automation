"""Auth core (B2, ADR-0030): sign up / in / out, password reset, sessions.

API-level happy + failure paths via the in-process client (with a capturing
mailer), plus service-level tests for the time-controlled cases (token expiry).
The app client commits to the shared test DB, so each test uses a unique email.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_token, hash_password, hash_token, verify_password
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.repositories.password_reset_token_repository import (
    PasswordResetTokenRepository,
)
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.errors import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidResetTokenError,
)

_SIGNUP = "/api/v1/auth/signup"
_SIGNIN = "/api/v1/auth/signin"
_SIGNOUT = "/api/v1/auth/signout"
_RESET_REQ = "/api/v1/auth/password-reset/request"
_RESET_CONFIRM = "/api/v1/auth/password-reset/confirm"
_ME = "/api/v1/auth/me"


def _email() -> str:
    return f"u-{uuid.uuid4().hex[:12]}@example.test"


class _CapturingMailer:
    """Test mailer: captures (email, token) instead of logging/sending."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_password_reset(self, *, email: str, token: str) -> None:
        self.sent.append((email, token))


@pytest_asyncio.fixture
async def auth(
    app_client: tuple[AsyncClient, FastAPI],
) -> tuple[AsyncClient, _CapturingMailer]:
    client, app = app_client
    mailer = _CapturingMailer()
    app.state.mailer = mailer
    return client, mailer


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- sign up -----------------------------------------------------------------


async def test_sign_up_returns_bearer_token_and_user(
    auth: tuple[AsyncClient, _CapturingMailer],
) -> None:
    client, _ = auth
    email = _email()
    resp = await client.post(_SIGNUP, json={"email": email, "password": "hunter2pw"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == email
    assert "password" not in resp.text and "hash" not in resp.text


async def test_sign_up_duplicate_email_is_409(
    auth: tuple[AsyncClient, _CapturingMailer],
) -> None:
    client, _ = auth
    email = _email()
    await client.post(_SIGNUP, json={"email": email, "password": "hunter2pw"})
    dupe = await client.post(_SIGNUP, json={"email": email, "password": "another1pw"})
    assert dupe.status_code == 409


async def test_sign_up_validation_is_422(
    auth: tuple[AsyncClient, _CapturingMailer],
) -> None:
    client, _ = auth
    bad_email = await client.post(
        _SIGNUP, json={"email": "nope", "password": "hunter2pw"}
    )
    assert bad_email.status_code == 422
    short_pw = await client.post(_SIGNUP, json={"email": _email(), "password": "short"})
    assert short_pw.status_code == 422


async def test_email_is_normalized_case_insensitive(
    auth: tuple[AsyncClient, _CapturingMailer],
) -> None:
    client, _ = auth
    base = _email()
    await client.post(_SIGNUP, json={"email": base.upper(), "password": "hunter2pw"})
    # Same address, different case → already registered, and sign-in works lower-cased.
    dupe = await client.post(_SIGNUP, json={"email": base, "password": "hunter2pw"})
    assert dupe.status_code == 409
    ok = await client.post(
        _SIGNIN, json={"email": base.upper(), "password": "hunter2pw"}
    )
    assert ok.status_code == 200


# --- sign in -----------------------------------------------------------------


async def test_sign_in_happy_and_failure_paths(
    auth: tuple[AsyncClient, _CapturingMailer],
) -> None:
    client, _ = auth
    email, pw = _email(), "hunter2pw"
    await client.post(_SIGNUP, json={"email": email, "password": pw})

    ok = await client.post(_SIGNIN, json={"email": email, "password": pw})
    assert ok.status_code == 200 and ok.json()["access_token"]

    wrong = await client.post(_SIGNIN, json={"email": email, "password": "wrongpass1"})
    assert wrong.status_code == 401

    unknown = await client.post(_SIGNIN, json={"email": _email(), "password": pw})
    assert unknown.status_code == 401


# --- protected endpoint + sign out -------------------------------------------


async def test_me_requires_authentication(
    auth: tuple[AsyncClient, _CapturingMailer],
) -> None:
    client, _ = auth
    assert (await client.get(_ME)).status_code == 401  # no token
    # a malformed/unknown bearer token is also rejected
    assert (await client.get(_ME, headers=_h("garbage"))).status_code == 401

    email = _email()
    token = (
        await client.post(_SIGNUP, json={"email": email, "password": "hunter2pw"})
    ).json()["access_token"]
    me = await client.get(_ME, headers=_h(token))
    assert me.status_code == 200 and me.json()["email"] == email


async def test_sign_out_revokes_the_session(
    auth: tuple[AsyncClient, _CapturingMailer],
) -> None:
    client, _ = auth
    token = (
        await client.post(_SIGNUP, json={"email": _email(), "password": "hunter2pw"})
    ).json()["access_token"]
    assert (await client.get(_ME, headers=_h(token))).status_code == 200
    out = await client.post(_SIGNOUT, headers=_h(token))
    assert out.status_code == 204
    # The token is dead immediately (real revocation, ADR-0030).
    assert (await client.get(_ME, headers=_h(token))).status_code == 401


# --- password reset ----------------------------------------------------------


async def test_password_reset_issue_consume_and_revoke(
    auth: tuple[AsyncClient, _CapturingMailer],
) -> None:
    client, mailer = auth
    email, old, new = _email(), "oldpass12", "newpass34"
    session_token = (
        await client.post(_SIGNUP, json={"email": email, "password": old})
    ).json()["access_token"]

    req = await client.post(_RESET_REQ, json={"email": email})
    assert req.status_code == 202
    assert len(mailer.sent) == 1 and mailer.sent[0][0] == email
    reset_token = mailer.sent[0][1]

    confirm = await client.post(
        _RESET_CONFIRM, json={"token": reset_token, "password": new}
    )
    assert confirm.status_code == 204

    # New password works, old fails, and the pre-reset session was revoked.
    new_ok = await client.post(_SIGNIN, json={"email": email, "password": new})
    assert new_ok.status_code == 200
    old_bad = await client.post(_SIGNIN, json={"email": email, "password": old})
    assert old_bad.status_code == 401
    assert (await client.get(_ME, headers=_h(session_token))).status_code == 401

    # Single-use: the same token cannot be replayed.
    replay = await client.post(
        _RESET_CONFIRM, json={"token": reset_token, "password": "third5678"}
    )
    assert replay.status_code == 400


async def test_password_reset_request_is_silent_for_unknown_email(
    auth: tuple[AsyncClient, _CapturingMailer],
) -> None:
    client, mailer = auth
    resp = await client.post(_RESET_REQ, json={"email": _email()})
    assert resp.status_code == 202  # same response as a known email (no enumeration)
    assert mailer.sent == []  # but nothing was issued/sent


async def test_password_reset_confirm_bad_token_is_400(
    auth: tuple[AsyncClient, _CapturingMailer],
) -> None:
    client, _ = auth
    resp = await client.post(
        _RESET_CONFIRM, json={"token": "not-a-real-token", "password": "newpass34"}
    )
    assert resp.status_code == 400


# --- service-level (time-controlled) -----------------------------------------


async def test_reset_password_rejects_expired_token(db_session: AsyncSession) -> None:
    user = await UserRepository(db_session).add(
        User(email=_email(), password_hash=hash_password("oldpass12"))
    )
    raw = generate_token()
    await PasswordResetTokenRepository(db_session).add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=datetime.now(UTC) - timedelta(hours=1),  # already expired
        )
    )
    service = AuthService(
        db_session,
        mailer=_CapturingMailer(),
        session_ttl_seconds=3600,
        reset_ttl_seconds=3600,
    )
    with pytest.raises(InvalidResetTokenError):
        await service.reset_password(raw, "newpass34")


def _service(
    session: AsyncSession, mailer: _CapturingMailer | None = None
) -> AuthService:
    return AuthService(
        session,
        mailer=mailer or _CapturingMailer(),
        session_ttl_seconds=3600,
        reset_ttl_seconds=3600,
    )


async def test_service_sign_up_and_sign_in(db_session: AsyncSession) -> None:
    svc = _service(db_session)
    email = _email()
    user, token1 = await svc.sign_up(email, "hunter2pw")
    assert user.email == email
    sessions = SessionRepository(db_session)
    assert await sessions.get_by_token_hash(hash_token(token1)) is not None

    with pytest.raises(EmailAlreadyRegisteredError):
        await svc.sign_up(email, "another1pw")

    user2, token2 = await svc.sign_in(email, "hunter2pw")
    assert user2.id == user.id and token2 != token1  # a fresh session each sign-in
    with pytest.raises(InvalidCredentialsError):
        await svc.sign_in(email, "wrongpass1")
    with pytest.raises(InvalidCredentialsError):
        await svc.sign_in(_email(), "hunter2pw")  # unknown account


async def test_service_sign_out_revokes_session(db_session: AsyncSession) -> None:
    svc = _service(db_session)
    _, token = await svc.sign_up(_email(), "hunter2pw")
    sessions = SessionRepository(db_session)
    assert await sessions.get_by_token_hash(hash_token(token)) is not None
    await svc.sign_out(token)
    assert await sessions.get_by_token_hash(hash_token(token)) is None
    await svc.sign_out(token)  # idempotent — no error on an already-dead token


async def test_service_request_reset_known_vs_unknown(db_session: AsyncSession) -> None:
    mailer = _CapturingMailer()
    svc = _service(db_session, mailer)
    email = _email()
    await svc.sign_up(email, "hunter2pw")

    await svc.request_password_reset(email)
    assert [e for e, _ in mailer.sent] == [email]
    await svc.request_password_reset(_email())  # unknown → silent, nothing issued
    assert len(mailer.sent) == 1


async def test_service_reset_consumes_and_revokes(db_session: AsyncSession) -> None:
    mailer = _CapturingMailer()
    svc = _service(db_session, mailer)
    email = _email()
    _, session_token = await svc.sign_up(email, "oldpass12")
    await svc.request_password_reset(email)
    reset_token = mailer.sent[0][1]

    await svc.reset_password(reset_token, "newpass34")
    user = await UserRepository(db_session).get_by_email(email)
    assert user is not None and verify_password(user.password_hash, "newpass34")
    sessions = SessionRepository(db_session)
    assert await sessions.get_by_token_hash(hash_token(session_token)) is None  # revoked

    with pytest.raises(InvalidResetTokenError):  # single-use
        await svc.reset_password(reset_token, "third5678")


def test_password_hashing_roundtrip() -> None:
    digest = hash_password("hunter2pw")
    assert digest != "hunter2pw"  # never plaintext
    assert verify_password(digest, "hunter2pw") is True
    assert verify_password(digest, "wrongpass1") is False
    assert verify_password("not-a-hash", "hunter2pw") is False
