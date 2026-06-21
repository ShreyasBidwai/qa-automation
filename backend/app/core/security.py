"""Auth primitives: password hashing + opaque-token generation (B2, ADR-0030).

Pure functions, no DB. Passwords are hashed with argon2id (memory-hard, no bcrypt
72-byte truncation). Session / reset tokens are random 256-bit URL-safe strings;
only their SHA-256 hash is ever persisted, so a DB leak exposes no live token and
nothing here logs a secret.
"""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # argon2id with library defaults (sane, memory-hard)


def hash_password(password: str) -> str:
    """Return an argon2id hash (includes algorithm + params + salt)."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """True iff ``password`` matches ``password_hash`` (constant-time in argon2)."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def generate_token() -> str:
    """A new opaque secret (256 bits, URL-safe) — the raw bearer/reset token."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """The at-rest representation of a token: its SHA-256 hex digest.

    Tokens are high-entropy random secrets, so a fast hash (not a slow KDF) is the
    right tool — it makes the stored value non-reversible without adding per-request
    cost. Lookups are by this digest.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
