"""The real (interactive) OtpProvider — prompt the tester for the code.

Used in real runs of ManualOtpStrategy: the tester reads the OTP/2FA code off
their own registered device and types it. The code is returned, never logged.
Tests inject a canned provider instead of this one.
"""

from __future__ import annotations

from .redact import redact_label
from .types import OtpRequest


def prompt_for_otp(request: OtpRequest) -> str:
    """Ask the operator for the one-time code on stdin (interactive use only)."""
    channel = f" via {request.channel}" if request.channel else ""
    account = redact_label(request.account)
    print(f"[auth] OTP/2FA required for {account}{channel}.")
    print("[auth] Read the code from your registered device and enter it below.")
    return input("[auth] code: ").strip()
