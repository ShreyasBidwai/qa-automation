"""Typed ingestion errors (Standards §7 — explicit, no bare except, no swallow)."""

from __future__ import annotations


class ExtractionError(Exception):
    """Base class for all extraction failures."""


class IngestionCommandError(ExtractionError):
    """A subprocess (artisan / php) could not be run or failed."""


class CommandTimeout(IngestionCommandError):
    """A subprocess exceeded its timeout."""


class CommandFailed(IngestionCommandError):
    """A subprocess exited non-zero."""

    def __init__(self, message: str, *, returncode: int | None = None) -> None:
        self.returncode = returncode
        super().__init__(message)


class RouteNotFound(ExtractionError):
    """No route matched the requested target (name, or method + URI)."""


class ActionResolutionError(ExtractionError):
    """The route's action is not a resolvable Controller@method."""


class ValidationExtractionError(ExtractionError):
    """The validation rules for an action could not be extracted/parsed."""


class GraphExtractionError(ExtractionError):
    """The whole-repo model/migration/action graph could not be parsed."""
