"""Minimum password policy for NEW passwords (B11, ADR-0046).

Hygiene, not a moat: an 8-character floor (matching what the UI implies) plus a
couple of cheap strength checks that blunt the obvious weak choices — all-numeric
and the most-guessed passwords. It is deliberately NOT a breach corpus or a
zxcvbn-grade estimator (documented in the ADR).

Applied to new passwords only — sign up, password-reset confirm, and the new
password on change — never to sign-in (which checks the stored hash) or to an
existing/current password. Errors are honest and user-facing.
"""

from __future__ import annotations

MIN_PASSWORD_LENGTH = 8

# A tiny blocklist of the most-guessed 8+ char passwords (compared lower-cased).
# Not a breach database — just the obvious ones a length floor alone lets through.
_COMMON_PASSWORDS = frozenset(
    {
        "password",
        "password1",
        "passw0rd",
        "12345678",
        "123456789",
        "1234567890",
        "qwertyui",
        "qwerty123",
        "11111111",
        "00000000",
        "iloveyou",
        "abc12345",
        "letmein1",
        "welcome1",
        "football",
        "baseball",
        "sunshine",
        "princess",
        "admin123",
        "trustno1",
    }
)


class WeakPasswordError(ValueError):
    """The password fails the minimum policy. The message is shown to the user."""


def validate_password(password: str) -> str:
    """Return ``password`` unchanged if it meets the policy, else raise.

    Order is most-actionable first: length, then all-numeric, then too-common.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if password.isdigit():
        raise WeakPasswordError(
            "Password can't be all numbers — add letters or symbols."
        )
    if password.lower() in _COMMON_PASSWORDS:
        raise WeakPasswordError(
            "That password is too common — choose something less guessable."
        )
    return password
