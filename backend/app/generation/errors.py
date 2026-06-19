"""Typed generation errors (Standards §7)."""

from __future__ import annotations


class GenerationError(Exception):
    """Base class for test-generation failures."""


class E2EPlanError(GenerationError):
    """An E2E plan could not be derived (e.g. the journey root is not a page)."""


class MutationGateError(GenerationError):
    """A plan contains a tautological assertion that no mutation could kill.

    The mutation-kill gate rejects assertions with no real check (e.g. merely
    "the page loaded"). CI-enforced — same thesis as the backend generator: an
    assertion that cannot fail is worthless (Standards §12).
    """
