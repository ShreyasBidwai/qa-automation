"""Typed DB-state-testing errors (Standards §7 — explicit, loud, never swallowed)."""

from __future__ import annotations


class DbStateError(Exception):
    """Base class for all DB-state-testing failures."""


class ProdTargetRefused(DbStateError):
    """The DB-state target is (or looks like) a production database — refused.

    The load-bearing safety rule (ADR-0043). This is NEVER softened or caught-and-
    continued: DB-state testing does not run unless the target is explicitly flagged
    disposable AND does not look prod. Erring toward refusing is the whole point.
    """


class WriteNotPermitted(DbStateError):
    """A write/read was attempted that the project's DB-state tier forbids.

    ``off`` permits nothing; ``read_only`` permits SELECT assertions but no writes
    to the disposable DB (ADR-0043).
    """


class UnsafeIdentifierError(DbStateError):
    """A table/column identifier failed validation (refused, not quoted-and-hoped)."""
