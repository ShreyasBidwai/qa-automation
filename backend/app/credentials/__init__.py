"""Target-account credentials: encrypt at rest, decrypt only at use (ADR-0053).

The account secret is encrypted before it touches the DB (``crypto``) and decrypted
only in memory at the point a run authenticates (``resolver``). No read/list/payload
path ever returns or decrypts it; it is never logged.
"""

from __future__ import annotations

from .crypto import (
    CredentialsDecryptError,
    CredentialsKeyError,
    decrypt_secret,
    encrypt_secret,
)
from .resolver import (
    ResolvedTargetLogin,
    resolve_target_auth_config,
    resolve_target_login,
)

__all__ = [
    "encrypt_secret",
    "decrypt_secret",
    "CredentialsKeyError",
    "CredentialsDecryptError",
    "ResolvedTargetLogin",
    "resolve_target_login",
    "resolve_target_auth_config",
]
