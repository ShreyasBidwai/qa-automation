"""Value objects + the PageFetcher contract for the runtime frontend crawler.

The crawler is stack-agnostic: it learns a target app's frontend by driving the
RUNNING app in a browser and reading the rendered DOM + network (never by parsing
per-stack source). A ``PageFetcher`` abstracts the browser: given a URL it returns
a ``PageSnapshot`` (what was rendered + which backend calls fired). The BFS,
caps, graph-building, and Brain writes live in the crawler and operate purely on
snapshots — so they are fully testable with injected snapshots and no real
browser (the real fetcher is the heavy lane).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class FormField:
    name: str
    type: str  # the input's type attribute (text|email|password|number|…)
    required: bool


@dataclass(frozen=True)
class FormSpec:
    action: str | None  # resolved form action URL (None → submits to current URL)
    method: str  # GET | POST (uppercased)
    fields: tuple[FormField, ...]


@dataclass(frozen=True)
class ElementSpec:
    tag: str  # button | a | …
    text: str  # trimmed accessible text/label


@dataclass(frozen=True)
class NetworkCall:
    """One backend call observed while the page loaded/initialised."""

    method: str  # uppercased HTTP method
    url: str  # absolute request URL
    resource_type: str  # playwright resource type (xhr|fetch|…)


@dataclass(frozen=True)
class PageSnapshot:
    """What the browser rendered for one page + the calls it made."""

    url: str  # the page's final URL (after redirects)
    title: str
    links: tuple[str, ...] = ()  # in-app hrefs discovered (absolute URLs)
    forms: tuple[FormSpec, ...] = ()
    elements: tuple[ElementSpec, ...] = ()
    network: tuple[NetworkCall, ...] = ()  # observed backend (xhr/fetch) calls


@dataclass(frozen=True)
class AuthConfig:
    """A configurable login step so authenticated pages are reachable.

    Credentials are passed to the browser layer over stdin and are NEVER logged
    (the crawler logs progress, never this object).
    """

    login_url: str
    username: str
    password: str
    username_selector: str = "input[type=email], input[name=email]"
    password_selector: str = "input[type=password], input[name=password]"
    submit_selector: str = "button[type=submit], input[type=submit]"


@dataclass(frozen=True)
class CrawlConfig:
    """Bounds + entry point for a crawl. Hard caps keep it safe and finite."""

    base_url: str  # the target origin; the crawl never leaves it
    start_path: str = "/"
    max_pages: int = 50
    max_depth: int = 3
    time_budget_s: float = 120.0
    auth: AuthConfig | None = None


@dataclass(frozen=True)
class CrawlResult:
    """Outcome of a crawl → Brain upsert (counts + the identities visited)."""

    pages: int  # page nodes upserted
    nav_edges: int  # page → page (navigates) edges upserted
    call_edges: int  # page → endpoint (calls) edges upserted, observed
    visited: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class PageFetcher(Protocol):
    """Drives the browser to one URL and returns what it rendered.

    The real implementation launches a browser; tests inject a fake that returns
    canned snapshots. ``fetch`` is synchronous — a crawl is sequential, so the
    blocking browser call simply sits between the crawler's async DB writes.
    """

    def fetch(self, url: str) -> PageSnapshot: ...
