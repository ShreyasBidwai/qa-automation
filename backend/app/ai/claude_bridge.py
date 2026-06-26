"""Client side of the Claude bridge — a ``CommandRunner`` that calls ``claude -p``
on the HOST over HTTP instead of running the CLI in the container.

Why: the runner container can't safely use the host's interactive Claude login.
Bind-mounting ``~/.claude`` read-write across a uid boundary lets the container's
``claude`` read-corrupt/rotate the shared OAuth token, logging the host out on every
``make up-real`` / ``down-real``. Instead the credentials stay on the host: a tiny
daemon (``app/bridge/server.py``, ``make bridge``) runs ``claude -p`` AS the
logged-in host user and exposes it over a token-guarded localhost endpoint. The
container calls that — it never touches ``~/.claude``.

The provider (:class:`~app.ai.claude_cli.ClaudeCliProvider`) is unchanged; only its
injected ``CommandRunner`` differs — the local subprocess is swapped for an HTTP
round trip that returns the SAME ``(returncode, stdout, stderr)`` shape, so envelope
parsing, usage capture, retries, and budgeting all work identically.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Sequence

from .claude_cli import CommandResult, CommandRunner
from .errors import AIInvocationError, AITimeout, AITransientError

# Headroom over the per-call timeout the daemon enforces, so the HTTP read waits for
# the daemon to return (with its own timed-out result) rather than racing it.
_HTTP_TIMEOUT_HEADROOM = 30.0


def _model_from_argv(argv: Sequence[str]) -> str:
    """The ``--model`` value the provider built into the argv (claude_cli.py).

    Only the prompt (stdin) and the model cross to the host — the bridge constructs
    the actual ``claude`` command itself, so the container can never run an arbitrary
    command on the host (no RCE via a forged argv)."""
    args = list(argv)
    if "--model" in args:
        index = args.index("--model")
        if index + 1 < len(args):
            return args[index + 1]
    raise AIInvocationError("claude bridge runner: no --model in argv")


def make_bridge_runner(bridge_url: str, token: str) -> CommandRunner:
    """A ``CommandRunner`` that POSTs ``{prompt, model}`` to the host bridge.

    Maps transport failures onto the provider's existing taxonomy: a bad token is a
    fatal config error (``AIInvocationError`` — retrying won't help); an unreachable
    or 5xx bridge is transient (``AITransientError`` — the provider's bounded retry
    rides over a restart); a read timeout is ``AITimeout``.
    """
    endpoint = bridge_url.rstrip("/") + "/generate"

    def runner(argv: Sequence[str], stdin_text: str, timeout: float) -> CommandResult:
        body = json.dumps(
            {
                "prompt": stdin_text,
                "model": _model_from_argv(argv),
                "timeout": timeout,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        try:
            with urllib.request.urlopen(
                request, timeout=timeout + _HTTP_TIMEOUT_HEADROOM
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise AIInvocationError(
                    "claude bridge rejected the token — check CLAUDE_BRIDGE_TOKEN "
                    "matches on the host (`make bridge`) and the runner"
                ) from exc
            raise AITransientError(f"claude bridge returned HTTP {exc.code}") from exc
        except TimeoutError as exc:
            raise AITimeout(f"claude bridge timed out after {timeout}s") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise AITransientError(
                f"claude bridge unreachable at {bridge_url} "
                f"(is `make bridge` running?): {exc}"
            ) from exc
        return CommandResult(
            returncode=int(payload.get("returncode", 1)),
            stdout=str(payload.get("stdout", "")),
            stderr=str(payload.get("stderr", "")),
        )

    return runner
