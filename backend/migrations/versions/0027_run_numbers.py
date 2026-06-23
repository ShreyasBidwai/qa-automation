"""friendly per-project run numbers: runs.run_number + projects.run_counter (ADR-0048)

Revision ID: 0027_run_numbers
Revises: 0026_incidents
Create Date: 2026-06-23

Forward-only and additive (Standards §14): a friendly per-project run number on
``runs`` (unique within a project) and the monotonic counter on ``projects`` that
hands them out atomically. Existing runs are backfilled DETERMINISTICALLY — numbered
1..N per project ordered by ``created_at`` then ``id`` — and each project's counter
is set to its run count so the next run continues the sequence. No new enum, no
destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0027_run_numbers"
down_revision: str | None = "0026_incidents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("run_number", sa.Integer(), nullable=True))
    op.add_column(
        "projects",
        sa.Column(
            "run_counter", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
    )

    # Backfill: number each project's runs 1..N by (created_at, id) — deterministic.
    op.execute(
        """
        WITH numbered AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY project_id ORDER BY created_at, id
                   ) AS rn
            FROM runs
        )
        UPDATE runs SET run_number = numbered.rn
        FROM numbered WHERE runs.id = numbered.id
        """
    )
    # Each project's counter continues from its highest assigned number.
    op.execute(
        """
        UPDATE projects SET run_counter = COALESCE(
            (SELECT MAX(run_number) FROM runs WHERE runs.project_id = projects.id), 0
        )
        """
    )

    op.create_index(
        "uq_runs_project_id_run_number",
        "runs",
        ["project_id", "run_number"],
        unique=True,
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_index("uq_runs_project_id_run_number", table_name="runs")
    op.drop_column("projects", "run_counter")
    op.drop_column("runs", "run_number")
