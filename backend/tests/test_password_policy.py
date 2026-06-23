"""Password policy (B11, ADR-0046) — new passwords only, voiced errors.

Unit tests pin the policy; endpoint tests confirm a weak password is rejected with
an honest message and a strong one is accepted, and that existing flows (a normal
strong password) are unchanged.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.password_policy import (
    MIN_PASSWORD_LENGTH,
    WeakPasswordError,
    validate_password,
)

# --- unit: the policy --------------------------------------------------------


def test_accepts_a_reasonable_password() -> None:
    assert validate_password("hunter2pw") == "hunter2pw"
    assert len("hunter2pw") >= MIN_PASSWORD_LENGTH


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("short", "at least"),  # below the length floor
        ("1234567", "at least"),  # 7 chars
        ("12345678", "all numbers"),  # long enough but all-numeric
        ("00000000", "all numbers"),
        ("password", "too common"),
        ("passw0rd", "too common"),
    ],
)
def test_rejects_weak_passwords_with_a_voiced_message(
    password: str, message: str
) -> None:
    with pytest.raises(WeakPasswordError, match=message):
        validate_password(password)


# --- endpoint: validation at the auth boundary -------------------------------


async def test_signup_rejects_weak_password_with_honest_error(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": "weak@example.test", "password": "12345678"},
    )
    assert resp.status_code == 422
    # The voiced policy message surfaces in the validation error (not a generic one).
    assert "all numbers" in str(resp.json())


async def test_signup_accepts_a_strong_password_unchanged(
    app_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = app_client
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": f"ok-{uuid.uuid4().hex[:10]}@example.test",
            "password": "str0ngpass",
        },
    )
    # Existing success flow unchanged: 201 + the same token/user shape.
    assert resp.status_code == 201
    body = resp.json()
    assert body["access_token"] and body["user"]["email"].startswith("ok-")
