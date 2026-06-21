"""Account surface (B3): profile update + change password (ADR-0030/0033).

API-level via the in-process client. The app client commits to the shared test DB,
so each test uses unique emails.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import AsyncClient

_SIGNUP = "/api/v1/auth/signup"
_SIGNIN = "/api/v1/auth/signin"
_ME = "/api/v1/auth/me"
_CHANGE_PW = "/api/v1/auth/change-password"


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _email() -> str:
    return f"acct-{uuid.uuid4().hex[:12]}@example.test"


async def _signup(client: AsyncClient, *, email: str, password: str) -> str:
    resp = await client.post(_SIGNUP, json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def test_update_profile_name_and_email(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    email = _email()
    token = await _signup(client, email=email, password="passw0rd1")

    named = await client.patch(_ME, json={"name": "Alice"}, headers=_h(token))
    assert named.status_code == 200 and named.json()["name"] == "Alice"

    new_email = _email()
    moved = await client.patch(_ME, json={"email": new_email}, headers=_h(token))
    assert moved.status_code == 200 and moved.json()["email"] == new_email
    # The new email is the live credential.
    assert (
        await client.post(_SIGNIN, json={"email": new_email, "password": "passw0rd1"})
    ).status_code == 200

    # name can be cleared with an explicit null; unspecified fields are untouched.
    cleared = await client.patch(_ME, json={"name": None}, headers=_h(token))
    assert cleared.status_code == 200 and cleared.json()["name"] is None
    assert cleared.json()["email"] == new_email


async def test_update_profile_email_conflict_is_409(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    taken = _email()
    await _signup(client, email=taken, password="passw0rd1")
    token = await _signup(client, email=_email(), password="passw0rd1")

    resp = await client.patch(_ME, json={"email": taken}, headers=_h(token))
    assert resp.status_code == 409


async def test_change_password_verifies_current_and_revokes_other_sessions(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    email, old, new = _email(), "oldpass12", "newpass34"
    here = await _signup(client, email=email, password=old)
    # A second, concurrent session (e.g. another device).
    other = (await client.post(_SIGNIN, json={"email": email, "password": old})).json()[
        "access_token"
    ]

    # Wrong current password is rejected.
    wrong = await client.post(
        _CHANGE_PW,
        json={"current_password": "nope12345", "new_password": new},
        headers=_h(here),
    )
    assert wrong.status_code == 400

    ok = await client.post(
        _CHANGE_PW,
        json={"current_password": old, "new_password": new},
        headers=_h(here),
    )
    assert ok.status_code == 204

    # This session stays valid; the other one is revoked.
    assert (await client.get(_ME, headers=_h(here))).status_code == 200
    assert (await client.get(_ME, headers=_h(other))).status_code == 401
    # New password works; the old one no longer does.
    assert (
        await client.post(_SIGNIN, json={"email": email, "password": new})
    ).status_code == 200
    assert (
        await client.post(_SIGNIN, json={"email": email, "password": old})
    ).status_code == 401


async def test_account_endpoints_require_auth(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    assert (await client.patch(_ME, json={"name": "x"})).status_code == 401
    assert (
        await client.post(
            _CHANGE_PW,
            json={"current_password": "x", "new_password": "passw0rd1"},
        )
    ).status_code == 401
