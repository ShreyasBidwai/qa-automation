"""case lineage: versioned, editable test cases with one-current invariant

Revision ID: 0007_case_lineage
Revises: 0006_node_content_sha
Create Date: 2026-06-18

Forward-only and additive (Standards §14): reconciles the existing
``test_cases`` schema with the lineage model (TRD §3 never-clobber). Adds only
what is missing — ``lineage_id``, ``is_current``, ``origin`` (+ enum), and
``edited_by`` — plus a lineage index and the partial unique index that enforces
EXACTLY ONE current version per (project_id, lineage_id). No destructive ops.

Backfill (no manual UPDATE needed): ``lineage_id`` is added NOT NULL with a
volatile ``gen_random_uuid()`` default, so Postgres rewrites the table and gives
each existing row its OWN distinct lineage; ``is_current`` defaults true, so each
existing case becomes the current version of its lineage; existing rows already
carry ``version = 1``. That is exactly "version 1 / current of their own lineage".
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_case_lineage"
down_revision: str | None = "0006_node_content_sha"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)

# Per-version provenance enum (values are the contract strings; see CaseOrigin).
case_origin = postgresql.ENUM(
    "generated", "edited", name="case_origin", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    case_origin.create(bind, checkfirst=True)

    op.add_column(
        "test_cases",
        sa.Column(
            "lineage_id",
            _UUID,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
    )
    op.add_column(
        "test_cases",
        sa.Column(
            "is_current",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "test_cases",
        sa.Column(
            "origin",
            case_origin,
            server_default=sa.text("'generated'"),
            nullable=False,
        ),
    )
    op.add_column(
        "test_cases",
        sa.Column("edited_by", sa.String(length=255), nullable=True),
    )

    # History lookups: all versions of a lineage, project-scoped.
    op.create_index(
        "ix_test_cases_project_id_lineage_id",
        "test_cases",
        ["project_id", "lineage_id"],
    )
    # The invariant: at most one current version per (project_id, lineage_id).
    op.create_index(
        "uq_test_cases_one_current",
        "test_cases",
        ["project_id", "lineage_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_index("uq_test_cases_one_current", table_name="test_cases")
    op.drop_index("ix_test_cases_project_id_lineage_id", table_name="test_cases")
    op.drop_column("test_cases", "edited_by")
    op.drop_column("test_cases", "origin")
    op.drop_column("test_cases", "is_current")
    op.drop_column("test_cases", "lineage_id")
    case_origin.drop(op.get_bind(), checkfirst=True)
