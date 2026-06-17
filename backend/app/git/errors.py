"""Typed git errors (Standards §7 — explicit, no bare except)."""

from __future__ import annotations


class GitError(Exception):
    """Base class for git-provider failures."""


class GitCheckoutError(GitError):
    """A clone/fetch/checkout step failed. Messages are credential-redacted."""
