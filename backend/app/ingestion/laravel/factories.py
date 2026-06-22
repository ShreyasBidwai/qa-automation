"""Detect whether a Laravel target defines model factories (B5→B6, ADR-0037).

Deterministic filesystem check. When a target has no factories, generated tests
must not call ``Model::factory()`` (they would hard-fail); the generator uses this
to steer the model off factories and to honestly skip residual factory-dependent
cases. Deep precondition seeding is deferred to B10.
"""

from __future__ import annotations

from pathlib import Path


def target_has_factories(repo_path: str) -> bool:
    """True iff the target repo defines at least one Eloquent model factory."""
    if not repo_path:
        return False
    factories = Path(repo_path) / "database" / "factories"
    return factories.is_dir() and any(factories.glob("*.php"))
