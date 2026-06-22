"""``project_documents`` — business docs attached to a project (B9).

Requirements / API contracts / user flows / acceptance criteria, attached to a
project and chunked + embedded into the Brain (``document_chunks``) so generation
can ground oracles in documented contracts. Structure only (Standards §5).
"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProjectScopedMixin


class ProjectDocument(Base, ProjectScopedMixin):
    __tablename__ = "project_documents"

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    # One of the known document kinds (validated at the API as a Literal): a free
    # String column so the set can grow without a migration.
    doc_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # The full document text (kept for re-chunking / display). Chunks live in
    # ``document_chunks``.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Hash of the content — idempotent re-upload + change detection.
    content_sha: Mapped[str] = mapped_column(String(64), nullable=False)
