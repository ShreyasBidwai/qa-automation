"""ORM models. Importing them here registers them on ``Base.metadata`` so
Alembic autogenerate sees the full schema.
"""

from __future__ import annotations

from .base import Base
from .project import Project

__all__ = ["Base", "Project"]
