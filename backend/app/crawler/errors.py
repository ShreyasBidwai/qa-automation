"""Typed crawler errors (Standards §7 — explicit, no bare except, no swallow)."""

from __future__ import annotations


class CrawlError(Exception):
    """Base class for runtime frontend-crawl failures."""


class CrawlConfigError(CrawlError):
    """The crawl configuration is invalid (e.g. start path off the target origin)."""


class PageFetchError(CrawlError):
    """The browser layer could not produce a usable snapshot for a URL.

    Raised when the crawl subprocess fails or returns output that is not a valid
    page snapshot — surfaced rather than silently skipped (Standards §7).
    """
