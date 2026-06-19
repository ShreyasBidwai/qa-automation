"""``auth_challenge_log`` — an append-only record of login-challenge encounters.

Every real login attempt against a live target appends one row: which challenge
the target presented (none/otp/2fa), the channel if observable, the outcome, and
a REDACTED account label. It NEVER stores the OTP code, password, or full
identifier (Standards §7/§18). Purpose: accumulate real data on which challenges
appear so we can later choose which automated AuthStrategy to build first (T4.2a;
see docs/parking-lot.md). Append-only — rows are facts, never updated.
"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProjectScopedMixin, pg_enum
from .enums import AuthChallenge


class AuthChallengeLog(Base, ProjectScopedMixin):
    __tablename__ = "auth_challenge_log"

    target_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    challenge: Mapped[AuthChallenge] = mapped_column(
        pg_enum(AuthChallenge, "auth_challenge"), nullable=False
    )
    # The delivery channel if observable (sms|email|app|…); null when unknown.
    channel: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # REDACTED tester identifier (e.g. "j•••@example.com"); never the full value.
    account_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Free-form result tag (success|failure); not an enum so it can grow.
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
