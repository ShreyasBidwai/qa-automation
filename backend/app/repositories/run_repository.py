"""Repository for ``runs`` (TRD §3)."""

from __future__ import annotations

from app.models.run import Run

from .base import ProjectScopedRepository


class RunRepository(ProjectScopedRepository[Run]):
    model = Run
