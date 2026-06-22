"""The non-prod safety gate — the load-bearing rule of B10 (ADR-0043).

DB-state testing NEVER runs against a production database. ``ensure_disposable``
is a structural hard gate: it refuses unless the target is EXPLICITLY flagged
disposable AND does not look like a production/staging DB. It errs toward refusing
— an unrecognized, non-local, non-marked target is refused, not assumed safe. Every
write path goes through this gate; there is no bypass.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import make_url

from .errors import ProdTargetRefused

# Substrings that mark a database as real/protected. If any appears in the host or
# database name we refuse REGARDLESS of the disposable flag — a mislabeled prod DB
# must not be writable. ``staging`` counts: it holds real-shaped data and real
# integrations (ADR-0043's rollback-limit honesty).
_PROD_MARKERS = ("prod", "production", "live", "staging", "stg")

# Hosts that are unambiguously a local/throwaway test environment.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "db", ""})

# Name markers that affirmatively identify a database as a throwaway. A non-local
# target must carry one of these in its name to be eligible (defense in depth on top
# of the explicit ``disposable`` flag).
_DISPOSABLE_MARKERS = ("disposable", "throwaway", "ephemeral", "dbstate", "scratch")


@dataclass(frozen=True)
class DisposableTarget:
    """A DB-state target. ``disposable`` is the EXPLICIT operator flag and the ONLY
    thing that opens the door to writes; absent/false → refused. ``url`` is still
    independently checked for prod-shape so the flag alone is never sufficient."""

    url: str
    disposable: bool
    label: str = ""


def _host_and_db(url: str) -> tuple[str, str]:
    """Best-effort (host, database) from a SQLAlchemy URL; sqlite has no host."""
    try:
        parsed = make_url(url)
    except Exception:  # noqa: BLE001 — an unparseable URL is treated as suspicious
        return ("", url)
    return (parsed.host or "", parsed.database or "")


def looks_prod(url: str) -> str | None:
    """A reason string if the URL looks production/staging-ish, else None."""
    host, database = _host_and_db(url)
    haystack = f"{host} {database}".lower()
    for marker in _PROD_MARKERS:
        if marker in haystack:
            return (
                f"target looks production-ish: matched {marker!r} "
                f"in host={host!r} db={database!r}"
            )
    return None


def ensure_disposable(target: DisposableTarget) -> None:
    """Refuse unless the target is explicitly disposable AND non-prod (ADR-0043).

    Three independent checks, all of which must pass:
      1. the explicit ``disposable`` flag is set (intent is required);
      2. nothing in the URL looks prod/staging (a mislabel can't slip through);
      3. the target is either a local host or affirmatively name-marked disposable
         (an unrecognized remote target is refused — err toward refusing).
    Raises ``ProdTargetRefused`` (never softened) on any failure.
    """
    if not target.disposable:
        raise ProdTargetRefused(
            "refusing DB-state target: not explicitly flagged disposable "
            "(set disposable=true only for a throwaway, non-prod database)"
        )

    reason = looks_prod(target.url)
    if reason is not None:
        raise ProdTargetRefused(f"refusing DB-state target: {reason}")

    host, database = _host_and_db(target.url)
    name_marked = any(m in f"{host} {database}".lower() for m in _DISPOSABLE_MARKERS)
    if host not in _LOCAL_HOSTS and not name_marked:
        raise ProdTargetRefused(
            "refusing DB-state target: neither a local host nor name-marked "
            f"disposable (host={host!r}, db={database!r}) — name it explicitly "
            "disposable to proceed"
        )
