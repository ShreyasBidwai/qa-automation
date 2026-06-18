"""Stack-agnostic runtime frontend crawler (T4.2, Architecture §4/§7/§9).

Learns a target app's frontend by driving the RUNNING app in a browser and
reading the rendered DOM + intercepted network — never by parsing per-stack
source — and writes pages + page→page + page→endpoint edges into the Brain.
"""

from __future__ import annotations

from .crawler import FrontendCrawler
from .errors import CrawlConfigError, CrawlError, PageFetchError
from .matching import EndpointMatcher
from .playwright_fetcher import PlaywrightPageFetcher
from .types import (
    AuthConfig,
    CrawlConfig,
    CrawlResult,
    ElementSpec,
    FormField,
    FormSpec,
    NetworkCall,
    PageFetcher,
    PageSnapshot,
)

__all__ = [
    "AuthConfig",
    "CrawlConfig",
    "CrawlConfigError",
    "CrawlError",
    "CrawlResult",
    "ElementSpec",
    "EndpointMatcher",
    "FormField",
    "FormSpec",
    "FrontendCrawler",
    "NetworkCall",
    "PageFetcher",
    "PageFetchError",
    "PageSnapshot",
    "PlaywrightPageFetcher",
]
