"""Screenshot capture storage + retrieval (ADR-0051).

A single indirection (``store_screenshot`` / ``get_screenshot``) over where the bytes
live — a local disk directory or an S3-compatible bucket, chosen by config — so call
sites never touch a path or a bucket, and the bytes are only ever served through the
authorized finding/run screenshot endpoints.
"""

from __future__ import annotations

from .storage import (
    get_screenshot,
    placeholder_screenshot,
    reset_backend_cache,
    store_project_screenshot,
    store_screenshot,
)

__all__ = [
    "store_screenshot",
    "store_project_screenshot",
    "get_screenshot",
    "placeholder_screenshot",
    "reset_backend_cache",
]
