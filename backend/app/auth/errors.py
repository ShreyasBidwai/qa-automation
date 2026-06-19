"""Typed auth errors (Standards §7 — explicit, no bare except, no swallow)."""

from __future__ import annotations


class AuthError(Exception):
    """Base class for authentication-seam failures."""


class AuthConfigError(AuthError):
    """An auth strategy was selected/used without the config or deps it needs."""


class LoginFailedError(AuthError):
    """A login attempt against the target did not produce a usable session.

    Raised after the attempt is recorded in the challenge log (so a failure is
    still observable for analysis), never with the secret in the message.
    """
