"""Test-case domain operations that are not persistence (Standards §5).

Currently the read-only, deterministic version diff (T3.4) consumed by the
re-generation merge engine (T3.3).
"""

from __future__ import annotations

from .diff import (
    COMPARED_FIELDS,
    CaseDiff,
    CaseDiffError,
    ChangeType,
    DiffEntry,
    IncomparableVersionsError,
    diff,
    diff_versions,
    render_diff,
)

__all__ = [
    "COMPARED_FIELDS",
    "CaseDiff",
    "CaseDiffError",
    "ChangeType",
    "DiffEntry",
    "IncomparableVersionsError",
    "diff",
    "diff_versions",
    "render_diff",
]
