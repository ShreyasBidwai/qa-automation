"""Generic, READ-ONLY git provider for ingestion (Architecture §4, TRD §7).

Lets ingestion run off a real remote (Gitea, or any git host) instead of a
hand-supplied local path. Deliberately generic git — no host-API features (repo
listing, webhooks); those are deferred until needed. There is no push path.
"""

from __future__ import annotations

from .cli import GitCliProvider
from .errors import GitCheckoutError, GitError
from .types import CheckoutHandle, GitProvider
from .url import authenticated_url, redact_url

__all__ = [
    "GitProvider",
    "GitCliProvider",
    "CheckoutHandle",
    "GitError",
    "GitCheckoutError",
    "authenticated_url",
    "redact_url",
]
