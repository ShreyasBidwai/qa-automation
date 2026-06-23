"""Screenshot capture storage + retrieval (ADR-0051).

A single indirection (``store_screenshot`` / ``get_screenshot``) over where the bytes
live — local disk tonight, object storage at deploy — so call sites never touch a
path and the bytes are only ever served through the authorized finding endpoint.
"""

from __future__ import annotations

from .storage import get_screenshot, placeholder_screenshot, store_screenshot

__all__ = ["store_screenshot", "get_screenshot", "placeholder_screenshot"]
