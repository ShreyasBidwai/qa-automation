"""Lightweight data factories for tests (Standards §15).

Unique slugs keep inserts collision-free across tests and parallel workers.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.models.project import Project


def make_project(**overrides: Any) -> Project:
    attrs: dict[str, Any] = {
        "name": "Test Project",
        "slug": f"test-{uuid.uuid4().hex[:12]}",
    }
    attrs.update(overrides)
    return Project(**attrs)
