"""Screenshot storage — the SINGLE indirection over where bytes live (ADR-0051).

Every screenshot write/read goes through ``store_screenshot`` / ``get_screenshot``
so call sites never touch a filesystem path. The implementation is local disk
tonight (a gitignored directory); the ref returned by ``store_screenshot`` is an
OPAQUE key (never a path), so swapping the backend out is a one-module change.

# TODO: swap to object storage at deploy. Local disk only works while capture and
# serve share a filesystem (the in-process stub/demo path). Real multi-container
# Playwright runs write on the runner and serve from the control plane, which need
# object storage — implement these two functions against it; nothing else changes.

Screenshots may contain sensitive app state (logged-in screens, real records), so
they are NEVER served from a static/public path: bytes are read here and streamed
only through the authorized ``GET /findings/{id}/screenshot`` endpoint.
"""

from __future__ import annotations

import logging
import re
import struct
import uuid
import zlib
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger("app.screenshots")

# A ref is an opaque 32-hex-char key (a stored file is ``<dir>/<ref>.png``). The
# strict shape also forbids any path-traversal input reaching the filesystem.
_REF = re.compile(r"\A[0-9a-f]{32}\Z")
# A PROJECT-scoped ref groups screenshots into a per-project folder (ADR-0051): the
# ref is ``<project_uuid>/<hex>`` and the file is ``<dir>/<project_uuid>/<hex>.png``.
# Both segments are strictly validated, so the ref can never traverse the filesystem.
_PROJECT_REF = re.compile(
    r"\A([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/([0-9a-f]{32})\Z"
)
_SUFFIX = ".png"


def _base_dir(base_dir: str | Path | None) -> Path:
    """The storage directory — the override (tests) or the configured default."""
    if base_dir is not None:
        return Path(base_dir)
    return Path(get_settings().screenshot_dir)


def store_screenshot(data: bytes, *, base_dir: str | Path | None = None) -> str:
    """Persist screenshot ``data`` and return an opaque ref (never a path).

    The caller stores the ref on the row; reading goes back through
    ``get_screenshot(ref)``. Raises on an I/O failure — the capture seam wraps this
    best-effort so a storage failure can never break a run (ADR-0051).
    """
    ref = uuid.uuid4().hex
    directory = _base_dir(base_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{ref}{_SUFFIX}").write_bytes(data)
    return ref


def store_project_screenshot(
    project_id: uuid.UUID, data: bytes, *, base_dir: str | Path | None = None
) -> str:
    """Persist screenshot ``data`` under a per-PROJECT folder; ref is ``<id>/<hex>``.

    The user-facing organisation the operator asked for: every project's testing
    screenshots live under ``<screenshot_dir>/<project_id>/``. The returned ref is
    still opaque (no absolute path) and round-trips through ``get_screenshot``.
    """
    ref = uuid.uuid4().hex
    directory = _base_dir(base_dir) / str(project_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{ref}{_SUFFIX}").write_bytes(data)
    return f"{project_id}/{ref}"


def get_screenshot(ref: str, *, base_dir: str | Path | None = None) -> bytes | None:
    """The bytes for ``ref``, or None if the ref is malformed or has no stored file.

    Accepts both a flat ref (``<hex>``) and a project-scoped ref (``<id>/<hex>``);
    both segments are strictly validated, so a ref can never escape the base dir.
    """
    if _REF.match(ref):
        path = _base_dir(base_dir) / f"{ref}{_SUFFIX}"
    elif match := _PROJECT_REF.match(ref):
        path = _base_dir(base_dir) / match.group(1) / f"{match.group(2)}{_SUFFIX}"
    else:
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def placeholder_screenshot(
    *, width: int = 320, height: int = 200, rgb: tuple[int, int, int] = (124, 31, 39)
) -> bytes:
    """A small, valid solid-colour PNG — the stub/demo failing finding's screenshot.

    Lets the UI screenshot affordance be built + demoed before real Playwright runs.
    Hand-rolled (no image lib): IHDR (8-bit RGB) + a single zlib-compressed IDAT of
    filter-0 rows + IEND.
    """

    def _chunk(tag: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + tag
            + body
            + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # colour type 2 = RGB
    row = b"\x00" + bytes(rgb) * width  # filter byte 0, then RGB pixels
    idat = zlib.compress(row * height, 9)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", idat)
        + _chunk(b"IEND", b"")
    )
