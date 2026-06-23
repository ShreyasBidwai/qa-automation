"""Incident fingerprint — the root-cause-key idea, pointed inward (ADR-0047).

A stable hash over exception type + the NORMALIZED raise location, so the SAME
failure groups across occurrences. The location is the deepest traceback frame's
file + function — deliberately WITHOUT the line number (which shifts on edits) and
with the build prefix stripped — so a given failure keeps one fingerprint across
runs and code changes. Deterministic.
"""

from __future__ import annotations

import hashlib
import traceback as _tb

# Build/install prefixes stripped from a frame's filename to a stable relative path.
_PATH_MARKERS = ("/app/", "/backend/", "/site-packages/")


def _normalize_location(filename: str, funcname: str) -> str:
    path = filename.replace("\\", "/")
    for marker in _PATH_MARKERS:
        index = path.find(marker)
        if index != -1:
            path = path[index + len(marker) :]
            break
    return f"{path}:{funcname}"


def location_of(exc: BaseException) -> str:
    """The normalized raise location (deepest frame) of ``exc``, or ``"unknown"``."""
    frames = _tb.extract_tb(exc.__traceback__)
    if not frames:
        return "unknown"
    last = frames[-1]
    return _normalize_location(last.filename, last.name)


def fingerprint(exception_type: str, location: str) -> str:
    """A stable 16-hex-char fingerprint over (exception type, normalized location)."""
    digest = hashlib.sha256(f"{exception_type}\n{location}".encode()).hexdigest()
    return digest[:16]


def fingerprint_for(exc: BaseException) -> str:
    """Convenience: the fingerprint of an exception from its type + raise location."""
    return fingerprint(type(exc).__name__, location_of(exc))
