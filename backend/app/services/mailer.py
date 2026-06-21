"""Mailer port + dev stub (B2). Pluggable behind a Protocol; real SMTP later.

The default ``StubMailer`` is the dev delivery channel: it LOGS the reset link
(there is no inbox in dev). This is the one deliberate place a reset token is
emitted — it stands in for "sending the email". Nothing else in the auth flow ever
logs a token (ADR-0030).
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger("app.mailer")


class Mailer(Protocol):
    """Sends transactional email. Swap the stub for real SMTP via composition."""

    async def send_password_reset(self, *, email: str, token: str) -> None: ...


class StubMailer:
    """Dev mailer: logs the reset token instead of sending an email."""

    async def send_password_reset(self, *, email: str, token: str) -> None:
        logger.info(
            "dev_mailer.password_reset (DEV ONLY — stands in for a sent email)",
            extra={"email": email, "reset_token": token},
        )


def build_mailer() -> Mailer:
    """The configured mailer. Default: the dev stub (no credentials needed)."""
    return StubMailer()
