"""durable jobs queue + operator flag (B4, ADR-0034/0035)

Revision ID: 0020_durable_jobs
Revises: 0019_orgs_rbac
Create Date: 2026-06-21

Forward-only and additive (Standards §14): the ``jobs`` table (the durable queue,
ADR-0034) with its ``job_kind`` / ``job_status`` enums, plus ``users.is_operator``
(the instance-level operator flag, ADR-0035). Does not alter existing tables beyond
the additive column. No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0020_durable_jobs"
down_revision: str | None = "0019_orgs_rbac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)
_JOB_KIND = postgresql.ENUM("ingest", "run", name="job_kind", create_type=False)
_JOB_STATUS = postgresql.ENUM(
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    name="job_status",
    create_type=False,
)


def _audit_columns() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.execute("CREATE TYPE job_kind AS ENUM ('ingest', 'run')")
    op.execute(
        "CREATE TYPE job_status AS ENUM "
        "('queued', 'running', 'succeeded', 'failed', 'cancelled')"
    )

    op.create_table(
        "jobs",
        *_audit_columns(),
        sa.Column("kind", _JOB_KIND, nullable=False),
        sa.Column(
            "status",
            _JOB_STATUS,
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column("project_id", _UUID, nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("run_id", _UUID, nullable=True),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
        sa.Column("detail", sa.String(length=255), nullable=True),
        sa.Column(
            "attempts", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=64), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_jobs_project_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_jobs_project_id", "jobs", ["project_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    # The claim path: queued rows whose backoff has elapsed, oldest first.
    op.create_index("ix_jobs_status_available_at", "jobs", ["status", "available_at"])

    op.add_column(
        "users",
        sa.Column(
            "is_operator",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_column("users", "is_operator")
    op.drop_index("ix_jobs_status_available_at", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_project_id", table_name="jobs")
    op.drop_table("jobs")
    op.execute("DROP TYPE job_status")
    op.execute("DROP TYPE job_kind")
