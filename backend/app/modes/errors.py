"""Typed Mode B errors (Standards §7 — explicit, no bare except)."""

from __future__ import annotations


class ModeBError(Exception):
    """A Mode B autonomous run could not be orchestrated.

    Raised for misconfiguration the orchestrator refuses to paper over — e.g. a
    ChangeImpact selection requested without a changeset/resolver — surfaced
    loudly rather than guessed (Standards §7).
    """
