"""PlaywrightPageFetcher — the real browser layer behind the crawler.

Reuses the T4.1 Playwright/browser infra (same pinned image + @playwright/test):
for each URL it runs the Node ``crawl_page.mjs`` driver as a subprocess, which
launches a browser (replaying the logged-in ``storageState`` when given),
navigates, intercepts xhr/fetch calls, reads the DOM, and prints one page
snapshot as JSON. The driver opens and closes its own browser per page, so
nothing leaks. Login itself is NOT done here — it is delegated once to an
AuthStrategy (T4.2a); this layer only replays the resulting session.

The Node driver is injectable so the JSON→snapshot parsing is unit-testable
without a real browser; the end-to-end browser path is the heavy e2e-runner lane.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .errors import PageFetchError
from .types import (
    ElementSpec,
    FormField,
    FormSpec,
    NetworkCall,
    PageSnapshot,
)

logger = logging.getLogger("app.crawler")

# (argv, cwd, stdin, timeout) -> (returncode, stdout, stderr). Injectable so the
# parser can be tested without spawning node/a browser.
NodeRunner = Callable[[Sequence[str], str, str, float], tuple[int, str, str]]

_DEFAULT_SCRIPT = "crawl_page.mjs"


def _run_node(
    argv: Sequence[str], cwd: str, stdin: str, timeout: float
) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            input=stdin,  # config (incl. credentials) over stdin, never argv
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PageFetchError(f"crawl driver timed out after {timeout}s") from exc
    except OSError as exc:
        raise PageFetchError(
            f"failed to run crawl driver: {type(exc).__name__}"
        ) from exc
    return completed.returncode, completed.stdout, completed.stderr


class PlaywrightPageFetcher:
    def __init__(
        self,
        *,
        base_url: str,
        node_project_dir: str = ".",
        script_path: str | None = None,
        wait_ms: int = 1500,
        timeout: float = 60.0,
        runner: NodeRunner = _run_node,
    ) -> None:
        self._base_url = base_url
        self._project_dir = Path(node_project_dir).resolve()
        self._script = script_path or str(self._project_dir / _DEFAULT_SCRIPT)
        self._wait_ms = wait_ms
        self._timeout = timeout
        self._runner = runner

    def fetch(
        self, url: str, *, storage_state: dict[str, Any] | None = None
    ) -> PageSnapshot:
        config: dict[str, Any] = {
            "url": url,
            "origin": self._base_url,
            "waitMs": self._wait_ms,
        }
        if storage_state:
            config["storageState"] = storage_state
        logger.info("crawl.fetch", extra={"url": url})

        argv = ["node", self._script]
        returncode, stdout, stderr = self._runner(
            argv, str(self._project_dir), json.dumps(config), self._timeout
        )
        if returncode != 0:
            raise PageFetchError(
                f"crawl driver exited {returncode} for {url}: {stderr.strip()[:500]}"
            )
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise PageFetchError(
                f"crawl driver produced invalid JSON for {url}"
            ) from exc
        return _parse_snapshot(data)


def _parse_snapshot(data: dict[str, Any]) -> PageSnapshot:
    if not isinstance(data, dict) or "url" not in data:
        raise PageFetchError("crawl snapshot missing required fields")
    forms = tuple(
        FormSpec(
            action=form.get("action"),
            method=str(form.get("method", "GET")).upper(),
            fields=tuple(
                FormField(
                    name=str(f.get("name", "")),
                    type=str(f.get("type", "text")),
                    required=bool(f.get("required", False)),
                )
                for f in form.get("fields", [])
                if isinstance(f, dict) and f.get("name")
            ),
        )
        for form in data.get("forms", [])
        if isinstance(form, dict)
    )
    elements = tuple(
        ElementSpec(tag=str(e.get("tag", "")), text=str(e.get("text", "")))
        for e in data.get("elements", [])
        if isinstance(e, dict)
    )
    network = tuple(
        NetworkCall(
            method=str(c.get("method", "")).upper(),
            url=str(c.get("url", "")),
            resource_type=str(c.get("resource_type", "")),
        )
        for c in data.get("network", [])
        if isinstance(c, dict) and c.get("url")
    )
    links = tuple(str(href) for href in data.get("links", []) if href)
    return PageSnapshot(
        url=str(data["url"]),
        title=str(data.get("title", "")),
        links=links,
        forms=forms,
        elements=elements,
        network=network,
    )
