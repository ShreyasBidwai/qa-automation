"""test_cases gen version tag — flywheel outcome attribution (ADR-0070)

Revision ID: 0040_testcase_gen_version
Revises: 0039_generation_signals
Create Date: 2026-07-08

Forward-only and additive (Standards §14). Two nullable columns recording the generation
prompt/strategy version that produced an AI-generated case; NULL for human/CSV cases.
Read at execution to attribute the case's outcome to its generation (C2).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0040_testcase_gen_version"
down_revision: str | None = "0039_generation_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "test_cases", sa.Column("gen_prompt_version", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "test_cases", sa.Column("gen_strategy", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("test_cases", "gen_strategy")
    op.drop_column("test_cases", "gen_prompt_version")
