"""internal incident capture: incidents (dev-suite slice 1)

Revision ID: 0026_incidents
Revises: 0025_db_state_tier
Create Date: 2026-06-23

Forward-only and additive (Standards §14): a standalone operator diagnostic log of
Polaris's own internal failures. NOT project-scoped — ``project_id``/``run_id`` are
nullable and carry NO foreign key (an incident outlives the entities it references,
so a deleted project must not erase the record). No new enum (``phase`` is a
validated string). No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0026_incidents"
down_revision: str | None = "0025_db_state_tier"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column(
            "id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("component", sa.String(length=128), nullable=True),
        sa.Column("project_id", _UUID, nullable=True),
        sa.Column("run_id", _UUID, nullable=True),
        sa.Column("exception_type", sa.String(length=256), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("traceback", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_incidents"),
    )
    op.create_index("ix_incidents_fingerprint", "incidents", ["fingerprint"])
    op.create_index("ix_incidents_created_at", "incidents", ["created_at"])
    op.create_index("ix_incidents_phase", "incidents", ["phase"])
    op.create_index("ix_incidents_project_id", "incidents", ["project_id"])


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_index("ix_incidents_project_id", table_name="incidents")
    op.drop_index("ix_incidents_phase", table_name="incidents")
    op.drop_index("ix_incidents_created_at", table_name="incidents")
    op.drop_index("ix_incidents_fingerprint", table_name="incidents")
    op.drop_table("incidents")
