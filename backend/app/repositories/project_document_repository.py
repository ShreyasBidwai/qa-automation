"""Repository for ``project_documents`` (B9) — project-scoped, RBAC-gated upstream.

Inherits add/get/list/count/delete (all project-scoped) from the base; deleting a
document cascades to its chunks (FK ON DELETE CASCADE).
"""

from __future__ import annotations

from app.models.project_document import ProjectDocument

from .base import ProjectScopedRepository


class ProjectDocumentRepository(ProjectScopedRepository[ProjectDocument]):
    model = ProjectDocument
