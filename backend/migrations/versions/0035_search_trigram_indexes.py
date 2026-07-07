"""pg_trgm + GIN indexes for the global name search (ADR-0068)

Revision ID: 0035_search_trigram_indexes
Revises: 0034_outcome_skipped
Create Date: 2026-07-07

Forward-only and additive (Standards §14). The command-palette search (⌘K) does a
deterministic ``ILIKE '%q%'`` substring match on ``projects.name`` and
``findings.title`` — a plain btree index only helps a prefix match, so this enables
the ``pg_trgm`` extension and adds a trigram GIN index on each column, letting an
arbitrary substring match use an index scan instead of a sequential scan as the
tables grow.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0035_search_trigram_indexes"
down_revision: str | None = "0034_outcome_skipped"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_projects_name_trgm "
        "ON projects USING gin (name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_findings_title_trgm "
        "ON findings USING gin (title gin_trgm_ops)"
    )


def downgrade() -> None:
    # Forward-only (Standards §14): the indexes are harmless to leave in place.
    pass
