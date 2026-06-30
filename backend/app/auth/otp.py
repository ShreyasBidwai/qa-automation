"""The real (interactive) OtpProvider — prompt the tester for the code.

Used in real runs of ManualOtpStrategy: the tester reads the OTP/2FA code off
their own registered device and types it. The code is returned, never logged.
Tests inject a canned provider instead of this one.
"""

from __future__ import annotations

from .errors import LoginFailedError
from .redact import redact_label
from .types import OtpRequest


def prompt_for_otp(request: OtpRequest) -> str:
    """Ask the operator for the one-time code on stdin (interactive use only)."""
    channel = f" via {request.channel}" if request.channel else ""
    account = redact_label(request.account)
    print(f"[auth] OTP/2FA required for {account}{channel}.")
    print("[auth] Read the code from your registered device and enter it below.")
    return input("[auth] code: ").strip()


def autonomous_otp_unavailable(request: OtpRequest) -> str:
    """OtpProvider for autonomous runs: there is no human to read the code.

    An autonomous crawl has no interactive operator, so a login that hits an
    OTP/2FA challenge cannot complete. Fail loudly (never block on stdin) — the
    crawl phase treats a login failure as a clean skip, so the run continues
    unauthenticated rather than hanging. Use a non-OTP test account for behind-the-
    gate coverage. The account is redacted; the (absent) code is never logged.
    """
    raise LoginFailedError(
        f"OTP/2FA required for {redact_label(request.account)} but this run is "
        "autonomous (no operator to enter a code); use a non-OTP test account"
    )
