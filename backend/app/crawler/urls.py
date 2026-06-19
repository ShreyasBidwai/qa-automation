"""Pure URL helpers for the crawler — origin scoping, dedup keys, page identity.

Deterministic and stdlib-only (urllib). Keeping these pure makes the BFS, the
origin guard, and node identity fully unit-testable without a browser.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit, urlunsplit


def _origin(url: str) -> tuple[str, str]:
    """(scheme, netloc) lowercased — the comparable origin of a URL."""
    parts = urlsplit(url)
    return parts.scheme.lower(), parts.netloc.lower()


def same_origin(url: str, base_url: str) -> bool:
    """True iff ``url`` is on the same scheme+host(+port) as ``base_url``."""
    return _origin(url) == _origin(base_url)


def normalize(url: str) -> str:
    """Canonical crawl key: scheme://netloc/path, dropping query + fragment.

    Bounds the crawl (query-param permutations collapse to one page) and is the
    dedup key for the BFS. A trailing slash on a non-root path is stripped so
    ``/users`` and ``/users/`` are one page.
    """
    parts = urlsplit(url)
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def identity(url: str) -> str:
    """Stable, origin-relative page identity (the page node's name).

    The path component only — so the same logical page reached via different
    origins/queries maps to one Brain node (idempotent across re-crawls).
    """
    path = urlsplit(url).path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path


def resolve(base_url: str, href: str) -> str:
    """Resolve a possibly-relative href against the page URL → absolute URL."""
    return urljoin(base_url, href)
