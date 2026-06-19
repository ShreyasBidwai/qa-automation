"""Redact a tester identifier to a safe label for the challenge log.

The full phone/email is a secret-adjacent identifier and must NEVER be persisted
or logged (Standards §18). This keeps just enough to recognise *which* account
was used — a few edge characters — and masks the rest. Pure + deterministic.
"""

from __future__ import annotations

_MASK = "•••"


def redact_label(identifier: str) -> str:
    """``jane@example.com`` → ``j•••@example.com``; ``+14155551234`` → ``+1•••34``.

    For an email, the local part is masked but the domain kept (useful, not
    sensitive). For anything else, keep a short prefix + the last 2 chars.
    """
    value = identifier.strip()
    if not value:
        return _MASK
    if "@" in value:
        local, _, domain = value.partition("@")
        head = local[:1] if local else ""
        return f"{head}{_MASK}@{domain}"
    keep_head = 2 if len(value) > 4 else 0
    return f"{value[:keep_head]}{_MASK}{value[-2:]}"
