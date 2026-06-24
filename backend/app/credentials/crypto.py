"""Symmetric encryption for target-account secrets (ADR-0053).

The ONLY module that turns a plaintext target secret into ciphertext and back.
Encryption is Fernet (AES-128-CBC + HMAC-SHA256, authenticated) with a key sourced
from config (``Settings.target_credentials_key``) — the environment / secret store,
NEVER the repo and NEVER hardcoded.

Hard rule (the whole point of this slice): if there is no key, encryption RAISES —
the caller must refuse to store rather than ever persist plaintext. The key itself is
a secret: it is never logged, and neither is any plaintext that passes through here
(errors carry no secret material — a bad token surfaces as Fernet's ``InvalidToken``,
which contains none).
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class CredentialsKeyError(RuntimeError):
    """No encryption key is configured — the write path must refuse (no plaintext)."""


class CredentialsDecryptError(RuntimeError):
    """A stored secret could not be decrypted (wrong key / tampered ciphertext)."""


def _fernet() -> Fernet:
    key = get_settings().target_credentials_key
    if not key:
        # Never fall back to plaintext or a default key — refuse loudly.
        raise CredentialsKeyError(
            "target_credentials_key is not configured; refusing to handle a secret"
        )
    return Fernet(key.encode("utf-8"))


def encrypt_secret(plaintext: str) -> bytes:
    """Encrypt a target secret for storage. Returns the Fernet token (ciphertext).

    Raises ``CredentialsKeyError`` when no key is configured — callers must let this
    propagate so nothing is stored in the clear.
    """
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_secret(token: bytes) -> str:
    """Decrypt a stored target secret to plaintext, IN MEMORY.

    Called only by the designated decrypt-at-use accessor (``app.credentials
    .resolver``) at the point a run authenticates — never by a read/list path.
    """
    try:
        return _fernet().decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        raise CredentialsDecryptError("stored secret could not be decrypted") from exc
