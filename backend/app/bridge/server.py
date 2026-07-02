"""Host-side Claude bridge daemon — runs ``claude -p`` AS the logged-in host user and
exposes it to the Polaris runner container over a token-guarded HTTP endpoint.

The credentials NEVER leave the host. The container calls this instead of running
``claude`` itself, so ``make up-real`` / ``down-real`` can't corrupt or rotate the
host's OAuth session (the cross-uid read-write ``~/.claude`` mount problem). Start it
with ``make bridge`` and keep it alive while the real stack runs.

SECURITY — this endpoint spends your Claude account:
- a bearer token is REQUIRED (``CLAUDE_BRIDGE_TOKEN``, shared with the container via
  ``.env``); constant-time compared;
- the request supplies only ``{prompt, model}`` — the bridge BUILDS the ``claude``
  argv itself from a validated model, so a container can request a generation but can
  NOT run an arbitrary command on the host (no RCE via a forged argv);
- concurrency is bounded + refresh-safe (``ConcurrencyGate``): up to
  ``CLAUDE_BRIDGE_CONCURRENCY`` calls run at once, but the OAuth token REFRESH stays
  serial (a stale window's first call runs alone to refresh), so concurrent refreshes
  can't race and invalidate each other. Default 1 ⇒ fully serial (safe);
- bind to a host-only / docker-gateway address — do not expose it beyond localhost.

Pure stdlib, no app imports: it runs on the host under bare ``python3``
(``python3 backend/app/bridge/server.py``, wired as ``make bridge``) and is unit-
tested via the importable pure core (``handle_generate``). It lives in its own
``app/bridge`` package — NOT ``app/ai`` — because running a script puts its directory
on ``sys.path[0]``, and ``app/ai/types.py`` would then shadow the stdlib ``types``.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# (prompt, model, timeout) -> {"returncode", "stdout", "stderr"}.
ClaudeRunner = Callable[[str, str, float], dict[str, Any]]

_DEFAULT_MODELS = "sonnet,opus,haiku"
# Official model ids (e.g. claude-opus-4-8) are allowed alongside the aliases without
# per-id config. The model only ever becomes a single ``--model`` argv element (never
# a shell string), so this is an allow-list, not an injection guard.
_MODEL_ID_RE = re.compile(r"claude-[A-Za-z0-9.\-]+")


class ConcurrencyGate:
    """Admit up to ``concurrency`` ``claude`` calls at once — but keep the OAuth
    token REFRESH serial, because concurrent refreshes invalidate each other's
    single-use refresh token (the reason the old design serialized everything).

    Reader/writer split: normal calls are readers (concurrent, bounded by a
    semaphore); the first call of each *stale window* is promoted to a writer — it
    runs EXCLUSIVELY (all peers drained, new ones held) so it refreshes the token
    with no race, then the window is "warm" and the next N calls run concurrently
    against the fresh token, so no concurrent call ever triggers a refresh.

    ``concurrency == 1`` short-circuits to fully serial (byte-for-byte the prior
    behaviour) — the safe, zero-risk default. See ADR-0057.
    """

    def __init__(self, concurrency: int, warm_interval: float) -> None:
        self._concurrency = max(1, concurrency)
        self._warm_interval = warm_interval
        self._cond = threading.Condition()
        self._slots = threading.Semaphore(self._concurrency)
        self._warming = False
        self._active = 0  # readers past the gate (running or queued on a slot)
        self._warmed_once = False
        self._last_warm = 0.0  # monotonic clock of the last successful warm-up

    def run(self, fn: Callable[[], Any]) -> Any:
        """Run ``fn()`` under the gate — exclusively when it is the warm-up call."""
        if self._concurrency == 1:
            with self._slots:  # exactly the old single-holder behaviour
                return fn()
        if self._claim_writer():
            try:
                return fn()  # exclusive: a real call that also refreshes the token
            finally:
                self._release_writer()
        else:
            try:
                with self._slots:  # bounded concurrency among readers
                    return fn()
            finally:
                self._release_reader()

    def _claim_writer(self) -> bool:
        """True ⇒ this call is the single-flight warm-up (run exclusive). False ⇒ a
        reader (already admitted). Blocks until the chosen lane is safe to enter."""
        with self._cond:
            stale = (not self._warmed_once) or (
                time.monotonic() - self._last_warm >= self._warm_interval
            )
            if stale and not self._warming:
                self._warming = True
                while self._active > 0:  # let in-flight readers drain
                    self._cond.wait()
                return True
            while self._warming:  # a warm-up is in progress — wait it out
                self._cond.wait()
            self._active += 1
            return False

    def _release_writer(self) -> None:
        with self._cond:
            self._warming = False
            self._warmed_once = True
            self._last_warm = time.monotonic()
            self._cond.notify_all()

    def _release_reader(self) -> None:
        with self._cond:
            self._active -= 1
            self._cond.notify_all()


# One gate for the process, sized from the environment. Default 1 ⇒ serial (safe);
# raise CLAUDE_BRIDGE_CONCURRENCY to fan out generation on your subscription.
_GATE = ConcurrencyGate(
    concurrency=int(os.environ.get("CLAUDE_BRIDGE_CONCURRENCY", "1")),
    warm_interval=float(os.environ.get("CLAUDE_BRIDGE_WARM_INTERVAL", "600")),
)


def is_authorized(auth_header: str, token: str) -> bool:
    """Constant-time bearer-token check; an unset token denies everything."""
    return bool(token) and hmac.compare_digest(auth_header, f"Bearer {token}")


def model_allowed(model: str, allowed: frozenset[str]) -> bool:
    return model in allowed or bool(_MODEL_ID_RE.fullmatch(model))


def run_claude(
    prompt: str,
    model: str,
    timeout: float,
    *,
    cli: str = "claude",
    max_timeout: float = 300.0,
) -> dict[str, Any]:
    """Run ``claude -p --output-format json --model <model>`` with the prompt on
    stdin and return its ``{returncode, stdout, stderr}``. The argv is a LIST (no
    shell) built here from the validated model — never from caller-supplied tokens."""
    argv = [cli, "-p", "--output-format", "json", "--model", model]

    def _invoke() -> dict[str, Any]:
        try:
            completed = subprocess.run(
                argv,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=min(timeout, max_timeout),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"returncode": 124, "stdout": "", "stderr": "claude timed out"}
        except FileNotFoundError:
            return {
                "returncode": 127,
                "stdout": "",
                "stderr": f"claude CLI not found on the host PATH ({cli!r})",
            }
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    # The gate keeps N calls concurrent but the OAuth refresh serial (see its docs).
    result: dict[str, Any] = _GATE.run(_invoke)
    return result


def handle_generate(
    payload: dict[str, Any],
    auth_header: str,
    *,
    token: str,
    allowed: frozenset[str],
    claude_runner: ClaudeRunner,
) -> tuple[int, dict[str, Any]]:
    """The pure request handler: authorize → validate → run. Returns (status, body).

    Kept free of HTTP/socket plumbing so it is exhaustively unit-testable with a fake
    ``claude_runner`` (no real ``claude``, no network)."""
    if not is_authorized(auth_header, token):
        return 401, {"error": "unauthorized"}
    try:
        prompt = str(payload["prompt"])
        model = str(payload["model"])
        timeout = float(payload.get("timeout", 120))
    except (KeyError, TypeError, ValueError):
        return 400, {"error": "bad request: expected {prompt, model}"}
    if not model_allowed(model, allowed):
        return 400, {"error": f"model not allowed: {model}"}
    return 200, claude_runner(prompt, model, timeout)


def _config() -> tuple[str, int, str, frozenset[str], str, float]:
    host = os.environ.get(
        "CLAUDE_BRIDGE_HOST", "0.0.0.0"
    )  # noqa: S104 — gated by token
    port = int(os.environ.get("CLAUDE_BRIDGE_PORT", "8787"))
    token = os.environ.get("CLAUDE_BRIDGE_TOKEN", "")
    allowed = frozenset(
        m.strip()
        for m in (os.environ.get("CLAUDE_BRIDGE_MODELS") or _DEFAULT_MODELS).split(",")
        if m.strip()
    )
    cli = os.environ.get("CLAUDE_BRIDGE_CLI", "claude")
    max_timeout = float(os.environ.get("CLAUDE_BRIDGE_MAX_TIMEOUT", "300"))
    return host, port, token, allowed, cli, max_timeout


def _make_handler() -> type[BaseHTTPRequestHandler]:
    _host, _port, token, allowed, cli, max_timeout = _config()

    class _Handler(BaseHTTPRequestHandler):
        def _reply(self, code: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 — http.server dispatch name
            if self.path.rstrip("/") == "/health":
                self._reply(200, {"status": "ok"})
            else:
                self._reply(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 — http.server dispatch name
            if self.path.rstrip("/") != "/generate":
                self._reply(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, json.JSONDecodeError):
                self._reply(400, {"error": "bad request: invalid JSON"})
                return
            status, body = handle_generate(
                payload,
                self.headers.get("Authorization", ""),
                token=token,
                allowed=allowed,
                claude_runner=lambda p, m, t: run_claude(
                    p, m, t, cli=cli, max_timeout=max_timeout
                ),
            )
            self._reply(status, body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return  # quiet by default — never log prompt content

    return _Handler


def main() -> None:
    host, port, token, allowed, _cli, _max = _config()
    if not token:
        raise SystemExit(
            "CLAUDE_BRIDGE_TOKEN must be set (shared with the runner via .env)"
        )
    server = ThreadingHTTPServer((host, port), _make_handler())
    print(  # noqa: T201 — operator-facing startup line
        f"claude-bridge listening on {host}:{port} "
        f"(models: {sorted(allowed)} + claude-* ids)"
    )
    # Security posture (architecture-review DO-NEXT #8): the endpoint spends your
    # Claude account. A non-loopback bind is reachable beyond localhost — needed so
    # the runner container can reach it via host.docker.internal (a loopback bind
    # would break that on Linux), but the operator must firewall the port to the
    # docker gateway / host and NOT expose it to a shared or public network.
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(  # noqa: T201 — operator-facing security warning
            f"  ⚠️  bound to {host} (all/other interfaces) — token-guarded, but "
            "firewall this port to the docker gateway; do NOT expose it publicly. "
            "Set CLAUDE_BRIDGE_HOST=127.0.0.1 if the runner is not containerised."
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
