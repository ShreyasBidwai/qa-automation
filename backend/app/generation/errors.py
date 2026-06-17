"""Typed generation errors (Standards §7)."""

from __future__ import annotations


class GenerationError(Exception):
    """Base class for test-generation failures."""
