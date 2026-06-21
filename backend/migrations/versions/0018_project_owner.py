"""project ownership: projects.owner_id → users (B2, ADR-0031)

Revision ID: 0018_project_owner
Revises: 0017_auth_users
Create Date: 2026-06-21

Forward-only and additive (Standards §14): a NULLABLE ``owner_id`` FK on
``projects`` → ``users(id)`` (``ON DELETE SET NULL``). Existing rows keep
``owner_id = NULL`` = "legacy / shared" (ADR-0031): no backfill is possible (no
user exists at migration time) and nulling would orphan the pre-auth demo data.
New projects are created owned; access is owner-or-shared. No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0018_project_owner"
down_revision: str | None = "0017_auth_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column("projects", sa.Column("owner_id", _UUID, nullable=True))
    op.create_foreign_key(
        "fk_projects_owner_id",
        "projects",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_index("ix_projects_owner_id", table_name="projects")
    op.drop_constraint("fk_projects_owner_id", "projects", type_="foreignkey")
    op.drop_column("projects", "owner_id")
