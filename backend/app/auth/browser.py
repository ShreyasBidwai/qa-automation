"""PlaywrightLoginBrowser — the real browser behind ManualOtpStrategy.

Reuses the T4.1 Playwright/browser infra: drives a Node ``auth_login.mjs`` script
that opens a browser, fills username/password, detects an OTP/2FA challenge, and
— when one appears — emits an ``otp_required`` event and waits for the code on
stdin. This Python side calls the injected ``OtpProvider`` for that code and
feeds it back, then the script submits it and returns the captured storageState.

The browser opens/closes its own browser, so nothing leaks. Credentials travel
over stdin (never argv/env) and are never logged. This is INTERIM infrastructure
(not exercised by the fast tests, which inject a fake browser); the strategy
logic + the contract are what the tests cover.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import replace
from pathlib import Path

from app.models.enums import AuthChallenge

from .errors import LoginFailedError
from .types import AuthConfig, LoginOutcome, OtpProvider, OtpRequest

logger = logging.getLogger("app.auth")

_DEFAULT_SCRIPT = "auth_login.mjs"


class PlaywrightLoginBrowser:
    def __init__(
        self,
        *,
        node_project_dir: str = ".",
        script_path: str | None = None,
        timeout: float = 180.0,
    ) -> None:
        self._project_dir = Path(node_project_dir).resolve()
        self._script = script_path or str(self._project_dir / _DEFAULT_SCRIPT)
        self._timeout = timeout

    def run_login(
        self,
        config: AuthConfig,
        otp_provider: OtpProvider,
        request: OtpRequest,
    ) -> LoginOutcome:
        # Config (incl. credentials + selectors) goes over stdin, never argv.
        spec = {
            "login_url": config.login_url,
            "username": config.username,
            "password": config.password,
            "username_selector": config.username_selector,
            "password_selector": config.password_selector,
            "submit_selector": config.submit_selector,
            "otp_selector": config.otp_selector,
            "otp_submit_selector": config.otp_submit_selector,
            "success_selector": config.success_selector,
            "timeout_ms": int(self._timeout * 1000),
        }
        logger.info("auth.browser_login_start", extra={"login_url": config.login_url})

        proc = subprocess.Popen(
            ["node", self._script],
            cwd=str(self._project_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdin = proc.stdin
        stdout = proc.stdout
        if stdin is None or stdout is None:  # pragma: no cover - defensive
            raise LoginFailedError("could not open pipes to the login driver")
        try:
            stdin.write(json.dumps(spec) + "\n")
            stdin.flush()
            for raw in stdout:
                line = raw.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue  # ignore any non-protocol stdout from node
                kind = event.get("event")
                if kind == "otp_required":
                    code = otp_provider(replace(request, channel=event.get("channel")))
                    stdin.write(json.dumps({"code": code}) + "\n")
                    stdin.flush()
                elif kind == "done":
                    return LoginOutcome(
                        storage_state=event.get("storageState", {}),
                        challenge=AuthChallenge(event.get("challenge", "none")),
                        channel=event.get("channel"),
                        success=bool(event.get("success")),
                    )
            raise LoginFailedError("login driver exited before completing")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                proc.kill()
