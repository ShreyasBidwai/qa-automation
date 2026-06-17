"""Typed embedding errors (Standards §7 — explicit, no bare except)."""

from __future__ import annotations


class EmbeddingError(Exception):
    """Base class for embedding-layer failures."""


class EmbeddingProviderError(EmbeddingError):
    """The embedding backend is unavailable or failed to produce vectors."""


class EmbeddingDimMismatch(EmbeddingError):
    """A produced vector's dimension does not match the configured/column dim."""
