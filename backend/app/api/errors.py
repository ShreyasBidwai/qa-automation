"""Typed API-layer errors (Standards §7)."""

from __future__ import annotations


class ApiError(Exception):
    """Base class for API-surface failures."""


class ApiConfigError(ApiError):
    """A required collaborator was not composed (e.g. mode_c without AI providers).

    Surfaced loudly so a misconfigured deployment fails a job explicitly rather
    than silently producing nothing (Standards §7).
    """
