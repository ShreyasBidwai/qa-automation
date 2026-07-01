"""Screenshot storage — the SINGLE indirection over where bytes live (ADR-0051).

Every screenshot write/read goes through ``store_screenshot`` / ``get_screenshot``
so call sites never touch a path or a bucket. The ref returned is an OPAQUE key
(never a path), so the backend is a config choice, not a code change:

- ``local`` — a gitignored on-disk directory. Only valid single-box, where capture
  (the runner) and serve (the control plane) share a filesystem — the dev/demo path.
- ``s3`` — an S3-compatible bucket (AWS S3, MinIO, any S3 API). The decoupled
  topology (ADR-0036) requires this: the runner writes a page/finding screenshot on
  its host and the control plane serves it from another; a shared bucket is the only
  place both can reach. Credentials come from boto3's standard env/IAM chain — never
  from our config, never in a URL, never logged.

Screenshots may contain sensitive app state (logged-in screens, real records), so
they are NEVER served from a static/public path (no public-read objects): bytes are
read here and streamed only through the authorized finding/run screenshot endpoints.
"""

from __future__ import annotations

import logging
import re
import struct
import uuid
import zlib
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

logger = logging.getLogger("app.screenshots")

# A ref is an opaque 32-hex-char key (stored object is ``<ref>.png``). The strict
# shape also forbids any path-traversal input reaching the filesystem/bucket.
_REF = re.compile(r"\A[0-9a-f]{32}\Z")
# A PROJECT-scoped ref groups screenshots per project (ADR-0051): the ref is
# ``<project_uuid>/<hex>`` and the object is ``<project_uuid>/<hex>.png``. Both
# segments are strictly validated, so a ref can never traverse the backend.
_PROJECT_REF = re.compile(
    r"\A([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/([0-9a-f]{32})\Z"
)
_SUFFIX = ".png"


class ScreenshotBackend(Protocol):
    """Where the bytes actually live. ``ref`` is an already-validated opaque key
    (``<hex>`` or ``<project_id>/<hex>``); the backend owns the ``.png`` layout."""

    def put(self, ref: str, data: bytes) -> None: ...

    def get(self, ref: str) -> bytes | None: ...


class LocalDiskStore:
    """On-disk backend: ``<base_dir>/<ref>.png`` (a project ref nests a subdir)."""

    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)

    def put(self, ref: str, data: bytes) -> None:
        path = self._base / f"{ref}{_SUFFIX}"
        path.parent.mkdir(parents=True, exist_ok=True)  # project subdir when nested
        path.write_bytes(data)

    def get(self, ref: str) -> bytes | None:
        try:
            return (self._base / f"{ref}{_SUFFIX}").read_bytes()
        except OSError:
            return None


class S3Store:
    """S3-compatible backend: object key ``<prefix>/<ref>.png`` in one bucket.

    Credentials/region resolution is boto3's job (env vars, shared config, or an
    instance/IRSA role) — we pass none here, so no secret touches our config or logs.
    A missing object reads as ``None``; other errors propagate to the best-effort
    capture seam (which logs and never breaks a run).
    """

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str,
        endpoint_url: str | None,
        region: str,
    ) -> None:
        if not bucket:
            raise ValueError("screenshot_s3_bucket must be set when storage=s3")
        # Lazy import so the (default) local path never pays boto3's import cost, and
        # a dev clone without boto3 still boots for the local backend.
        import boto3  # noqa: PLC0415 — intentionally lazy

        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._client = boto3.client(
            "s3", endpoint_url=endpoint_url or None, region_name=region
        )

    def _key(self, ref: str) -> str:
        name = f"{ref}{_SUFFIX}"
        return f"{self._prefix}/{name}" if self._prefix else name

    def put(self, ref: str, data: bytes) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=self._key(ref),
            Body=data,
            ContentType="image/png",
        )

    def get(self, ref: str) -> bytes | None:
        from botocore.exceptions import ClientError  # noqa: PLC0415 — lazy

        try:
            obj = self._client.get_object(Bucket=self._bucket, Key=self._key(ref))
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"NoSuchKey", "404", "NoSuchBucket"}:
                return None
            raise
        data = obj["Body"].read()
        return bytes(data)


@lru_cache(maxsize=1)
def _cached_s3_store(
    bucket: str, endpoint_url: str | None, region: str, prefix: str
) -> S3Store:
    return S3Store(
        bucket=bucket, prefix=prefix, endpoint_url=endpoint_url, region=region
    )


def reset_backend_cache() -> None:
    """Drop the cached S3 client. For tests that swap backends between cases (so each
    builds a fresh client inside its own mock context)."""
    _cached_s3_store.cache_clear()


def _backend(base_dir: str | Path | None) -> ScreenshotBackend:
    """The active backend: an explicit ``base_dir`` (tests) forces local disk;
    otherwise the configured backend (``local`` on-disk, or ``s3``)."""
    if base_dir is not None:
        return LocalDiskStore(base_dir)
    settings = get_settings()
    if getattr(settings, "screenshot_storage", "local") == "s3":
        return _cached_s3_store(
            settings.screenshot_s3_bucket,
            settings.screenshot_s3_endpoint_url,
            settings.screenshot_s3_region,
            settings.screenshot_s3_prefix,
        )
    return LocalDiskStore(settings.screenshot_dir)


def store_screenshot(data: bytes, *, base_dir: str | Path | None = None) -> str:
    """Persist screenshot ``data`` and return an opaque ref (never a path/bucket key).

    The caller stores the ref on the row; reading goes back through
    ``get_screenshot(ref)``. Raises on a storage failure — the capture seam wraps this
    best-effort so a failure can never break a run (ADR-0051).
    """
    ref = uuid.uuid4().hex
    _backend(base_dir).put(ref, data)
    return ref


def store_project_screenshot(
    project_id: uuid.UUID, data: bytes, *, base_dir: str | Path | None = None
) -> str:
    """Persist screenshot ``data`` under a per-PROJECT namespace; ref is ``<id>/<hex>``.

    The user-facing organisation the operator asked for: every project's testing
    screenshots live together (a folder on disk, a key prefix in S3). The returned ref
    is still opaque (no absolute path) and round-trips through ``get_screenshot``.
    """
    ref = f"{project_id}/{uuid.uuid4().hex}"
    _backend(base_dir).put(ref, data)
    return ref


def get_screenshot(ref: str, *, base_dir: str | Path | None = None) -> bytes | None:
    """The bytes for ``ref``, or None if the ref is malformed or has no stored object.

    Accepts both a flat ref (``<hex>``) and a project-scoped ref (``<id>/<hex>``);
    both segments are strictly validated, so a ref can never escape its namespace.
    """
    if not (_REF.match(ref) or _PROJECT_REF.match(ref)):
        return None
    return _backend(base_dir).get(ref)


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
